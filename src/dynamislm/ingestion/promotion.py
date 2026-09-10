"""The RES-63 canonical replay and conjunctive promotion authority."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

from dynamislm.ingestion.contracts import (
    CanonicalEmpiricalArtifactReceipt,
    CanonicalEmpiricalRecord,
    DatasetQualificationReceipt,
    PromotionDecision,
    PromotionStatus,
    VariableResolutionStatus,
)
from dynamislm.ingestion.storage import (
    ensure_data_tree,
    file_digest_and_size,
    relative_data_path,
    verify_file,
    write_external_json,
)
from dynamislm.measurement.identity import ScientificIdentifier
from dynamislm.serialization import canonical_data, canonical_hash, canonical_json

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
    lineage = record.lineage
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
    if len(lineage) != len(required_prefixes):
        return False
    return all(
        value.startswith(prefix) for value, prefix in zip(lineage, required_prefixes, strict=True)
    )


def _promotion_reason(gate_name: str) -> str:
    return f"{gate_name.upper()}_FAILED"


def canonical_record_payload(record: CanonicalEmpiricalRecord) -> dict[str, object]:
    """Build the privacy-minimized JSONL payload for one canonical record.

    The complete typed qualification decisions remain in their receipts and
    are referenced by stable IDs here; repeating those large decision trees in
    every row would add no lineage authority.
    """

    variable_identity = canonical_data(record.variable_identity)
    if not isinstance(variable_identity, dict):
        raise ValueError("source variable identity did not serialize to an object")
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
        "variable_identity": variable_identity,
        "source_reported_value": record.source_reported_value,
        "population_decision_id": record.population_decision.decision_id.stable_id,
        "source_decision_id": record.source_decision.decision_id.stable_id,
        "mapping_version": record.mapping_version,
        "lineage": record.lineage,
    }


def decide_promotion(
    *,
    runtime_integrity_pass: bool,
    source_qualified: bool,
    population_qualified: bool,
    raw_bytes_verified: bool,
    source_version_verified: bool,
    license_captured: bool,
    variable_identity_resolved: bool,
    football_world_mapping_resolved: bool,
    lineage_complete: bool,
) -> PromotionDecision:
    """Return the only promotion decision constructed by RES-63.

    There is intentionally no override parameter.  ``PromotionDecision``
    recomputes the same conjunction during direct construction and V3 decode.
    """

    gates = (
        ("runtime_integrity", runtime_integrity_pass),
        ("source_qualified", source_qualified),
        ("population_qualified", population_qualified),
        ("raw_bytes", raw_bytes_verified),
        ("source_version", source_version_verified),
        ("license", license_captured),
        ("variable_identity", variable_identity_resolved),
        ("football_world_mapping", football_world_mapping_resolved),
        ("lineage", lineage_complete),
    )
    flags = tuple(value for _, value in gates)
    reasons = tuple(_promotion_reason(name) for name, value in gates if not value)
    decision_key = canonical_hash(
        {name: value for (name, _), value in zip(gates, flags, strict=True)}
    )
    decision_id = ScientificIdentifier(
        "dynamislm",
        "promotion-decision",
        decision_key.removeprefix("sha256:"),
        "1.0.0",
    )
    can_promote = all(flags)
    return PromotionDecision(
        decision_id=decision_id,
        status=PromotionStatus.PROMOTED if can_promote else PromotionStatus.QUARANTINED,
        can_promote=can_promote,
        runtime_integrity_pass=runtime_integrity_pass,
        source_qualified=source_qualified,
        population_qualified=population_qualified,
        raw_bytes_verified=raw_bytes_verified,
        source_version_verified=source_version_verified,
        license_captured=license_captured,
        variable_identity_resolved=variable_identity_resolved,
        football_world_mapping_resolved=football_world_mapping_resolved,
        lineage_complete=lineage_complete,
        reason_codes=reasons,
    )


def promotion_from_qualification(
    qualification: DatasetQualificationReceipt,
    *,
    runtime_integrity_pass: bool,
    source_version_verified: bool,
    lineage_complete: bool,
) -> PromotionDecision:
    """Lift a qualification receipt through the same promotion conjunction."""

    if not isinstance(qualification, DatasetQualificationReceipt):
        raise ValueError("qualification must be a DatasetQualificationReceipt")
    variable_resolved = qualification.variable_identity_status in (
        VariableResolutionStatus.RESOLVED,
        VariableResolutionStatus.PARTIAL,
    )
    football_resolved = qualification.football_mapping_status is VariableResolutionStatus.RESOLVED
    return decide_promotion(
        runtime_integrity_pass=runtime_integrity_pass,
        source_qualified=(
            qualification.source_decision is not None
            and qualification.source_decision.passed
            and qualification.actual_observed_data
            and qualification.performance_science_relevance
        ),
        population_qualified=(
            qualification.population_decision is not None
            and qualification.population_decision.passed
        ),
        raw_bytes_verified=qualification.artifact_sha256 is not None,
        source_version_verified=source_version_verified,
        license_captured=qualification.license_captured,
        variable_identity_resolved=variable_resolved,
        football_world_mapping_resolved=football_resolved,
        lineage_complete=lineage_complete,
    )


def canonical_jsonl_bytes(records: Iterable[CanonicalEmpiricalRecord]) -> bytes:
    """Return stable UTF-8 JSONL bytes with deterministic record ordering."""

    materialized = tuple(records)
    if any(not isinstance(record, CanonicalEmpiricalRecord) for record in materialized):
        raise ValueError("canonical JSONL records must contain CanonicalEmpiricalRecord values")
    for record in materialized:
        if not record.population_decision.passed or not record.source_decision.passed:
            raise ValueError("non-qualified source or population cannot enter canonical output")
        if not _lineage_is_complete(record):
            raise ValueError("canonical record lineage is incomplete")
        if record.variable_identity.resolution_status in (
            VariableResolutionStatus.UNRESOLVED,
            VariableResolutionStatus.QUARANTINED,
        ):
            raise ValueError("unresolved source variable cannot enter canonical output")
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


def write_canonical_jsonl(
    records: Iterable[CanonicalEmpiricalRecord],
    *,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    mapping_version: str,
    metadata_snapshot_sha256: str | None = None,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> CanonicalEmpiricalArtifactReceipt:
    """Atomically write the full real canonical artifact outside Git."""

    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    materialized_records = tuple(records)
    for record in materialized_records:
        if record.source_identity.source_id != source_id:
            raise ValueError("canonical record source ID does not match artifact source ID")
        if record.version_identity.repository_version != source_version:
            raise ValueError("canonical record version does not match artifact source version")
        if record.mapping_version != mapping_version:
            raise ValueError("canonical record mapping version does not match artifact mapping")
        if record.raw_artifact_sha256 != (
            "sha256:" + raw_source_sha256.removeprefix("sha256:").lower()
        ):
            raise ValueError("canonical record raw artifact does not match artifact source")
    content = canonical_jsonl_bytes(materialized_records)
    record_count = content.count(CANONICAL_JSONL_NEWLINE.encode("utf-8"))
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    safe_source = "".join(
        character if character.isalnum() or character in "._-" else "-" for character in source_id
    )
    safe_mapping = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in mapping_version
    )
    relative_path = f"canonical/{safe_source}-{source_version}-{safe_mapping}.jsonl"
    target = (resolved_data_root / relative_path).resolve(strict=False)
    if relative_data_path(resolved_data_root, target) != relative_path:
        raise ValueError("canonical artifact path escaped DYNAMISLM_DATA_ROOT")
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    if target.exists():
        existing_digest, _ = file_digest_and_size(target)
        if existing_digest != digest:
            temporary.unlink()
            raise ValueError("existing canonical path has a different content hash")
        temporary.unlink()
    else:
        os.replace(temporary, target)
    receipt = CanonicalEmpiricalArtifactReceipt(
        source_id=source_id,
        source_version=source_version,
        raw_source_sha256=raw_source_sha256,
        canonical_artifact_sha256=digest,
        canonical_record_count=record_count,
        mapping_version=mapping_version,
        relative_path=relative_path,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
    )
    write_external_json(
        resolved_data_root,
        f"receipts/{safe_source}-{source_version}-{safe_mapping}-canonical.json",
        receipt,
    )
    return receipt


def canonical_replay_digest(records: Iterable[CanonicalEmpiricalRecord]) -> str:
    """Hash the deterministic JSONL representation without timestamps or paths."""

    return f"sha256:{hashlib.sha256(canonical_jsonl_bytes(records)).hexdigest()}"


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
) -> None:
    """Fail closed when two canonicalizations of identical bytes diverge."""

    first_records = tuple(first)
    second_records = tuple(second)
    if canonical_replay_digest(first_records) != canonical_replay_digest(second_records):
        raise ValueError("canonical replay digests differ")


__all__ = [
    "CANONICAL_JSONL_NEWLINE",
    "MAPPING_VERSION_PREFIX",
    "build_raw_to_canonical_lineage",
    "canonical_jsonl_bytes",
    "canonical_record_payload",
    "canonical_replay_digest",
    "decide_promotion",
    "promotion_from_qualification",
    "validate_canonical_replay",
    "verify_canonical_artifact",
    "write_canonical_jsonl",
]
