#!/usr/bin/env python3
"""Offline deterministic replay and report regeneration for RES-63."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dynamislm.ingestion.adapters.mendeley_rpl import (
    SOURCE_B_ID,
    SOURCE_B_REGISTERED_FILE,
    SOURCE_B_VERSION,
    inspect_workbook,
    source_b_quarantine,
)
from dynamislm.ingestion.adapters.mendeley_turkish_super_league import (
    SOURCE_C_ID,
    SOURCE_C_REGISTERED_FILE,
    classify_source_c_granularity,
    inspect_source_c,
    source_c_quarantine,
)
from dynamislm.ingestion.adapters.unifesp_serie_a import (
    SOURCE_A_ID,
    SOURCE_A_LANDING_PAGE,
    SOURCE_A_MAPPING_VERSION,
    SOURCE_A_REGISTERED_FILE,
    SOURCE_A_SOURCE,
    SOURCE_A_VERSION,
    inspect_source_a,
    map_source_a_records,
    source_a_file_metadata,
    source_a_metadata_conflicts,
    source_a_population_and_source_decisions,
    source_a_representation_audit,
    source_a_variable_registry,
)
from dynamislm.ingestion.adapters.zenodo_ekstraklasa import (
    SOURCE_D_ID,
    SOURCE_D_REGISTERED_FILE,
    inspect_source_d_archive,
    source_d_quarantine,
    zenodo_file_metadata,
)
from dynamislm.ingestion.contracts import (
    ArtifactAcquisitionReceipt,
    CanonicalEmpiricalRecord,
    DatasetQualificationReceipt,
    FileRepresentation,
    QuarantineReceipt,
    RegisteredDatasetFileIdentity,
    SavedOriginalVerificationReceipt,
    VariableResolutionStatus,
    VerifiedRawArtifact,
    WorkbookSchema,
)
from dynamislm.ingestion.promotion import (
    validate_canonical_records,
    verify_canonical_artifact,
    write_canonical_jsonl,
)
from dynamislm.ingestion.qualification import qualify_dataset
from dynamislm.ingestion.registry import (
    dataset_license_identity,
    load_dataset_registry,
    registry_file_entries,
)
from dynamislm.ingestion.storage import (
    assert_data_path_contained,
    data_root_inventory,
    file_digest_and_size,
    resolve_data_root,
)
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.serialization import canonical_data, from_canonical_json

_REPOSITORY_ROOT = Path(__file__).parents[1].resolve()
_REPORT_NAMES = (
    "source-a-artifact-receipt.json",
    "source-a-metadata-conflicts.json",
    "source-a-qualification.json",
    "source-a-schema.json",
    "source-a-variable-identities.json",
    "source-b-qualification.json",
    "source-b-schema.json",
    "source-c-quarantine.json",
    "source-d-quarantine.json",
)
_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_slug(value: str) -> str:
    slug = _SAFE_SLUG_RE.sub("-", value).strip("-")
    return slug or "artifact"


def _raw_path(data_root: Path, registered: RegisteredDatasetFileIdentity) -> Path:
    digest = registered.expected_sha256.removeprefix("sha256:")
    return assert_data_path_contained(
        data_root,
        data_root / "objects" / "sha256" / digest[:2] / digest,
    )


def _raw_relative_path(registered: RegisteredDatasetFileIdentity) -> str:
    digest = registered.expected_sha256.removeprefix("sha256:")
    return f"objects/sha256/{digest[:2]}/{digest}"


def _typed_receipt_path(source_id: str, source_version: str, suffix: str) -> str:
    return f"receipts/{_safe_slug(source_id)}-{_safe_slug(source_version)}-{suffix}.json"


def _read_text(data_root: Path, relative_path: str) -> str:
    path = assert_data_path_contained(data_root, data_root / relative_path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"required persisted external receipt is unreadable: {relative_path}"
        ) from exc


def _read_typed(
    data_root: Path,
    relative_path: str,
    expected_type: type[Any],
) -> Any:
    return from_canonical_json(_read_text(data_root, relative_path), expected_type)


def _metadata_digest(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _read_metadata_snapshot(
    data_root: Path,
    *,
    source_id: str,
    source_version: str,
    expected_sha256: str,
) -> dict[str, Any]:
    digest = expected_sha256.removeprefix("sha256:").lower()
    relative_path = f"metadata/{_safe_slug(source_id)}-{_safe_slug(source_version)}-{digest}.json"
    raw = _read_text(data_root, relative_path)
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"metadata snapshot is not valid JSON: {relative_path}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("metadata snapshot must be an object")
    if _metadata_digest(metadata) != f"sha256:{digest}":
        raise ValueError("persisted metadata snapshot digest differs from its registered identity")
    return metadata


def _verify_persisted_metadata_file_identity(
    metadata: dict[str, Any],
    registered: RegisteredDatasetFileIdentity,
) -> None:
    details = metadata.get("content_details")
    if not isinstance(details, dict):
        raise ValueError("persisted Mendeley metadata lacks content_details")
    observed_file_id = metadata.get("id", metadata.get("file_id"))
    if observed_file_id != registered.provider_file_id:
        raise ValueError("persisted provider metadata file ID differs from registry")
    if metadata.get("filename") != registered.filename:
        raise ValueError("persisted provider metadata filename differs from registry")
    if metadata.get("size") != registered.expected_byte_size:
        raise ValueError("persisted provider metadata byte size differs from registry")
    observed_sha256 = details.get("sha256_hash")
    if not isinstance(observed_sha256, str):
        raise ValueError("persisted provider metadata lacks its SHA-256 observation")
    if observed_sha256.lower() != registered.expected_sha256.removeprefix("sha256:").lower():
        raise ValueError("persisted provider metadata SHA-256 differs from registry")


def _verify_persisted_zenodo_metadata(
    metadata: dict[str, Any],
    registered: RegisteredDatasetFileIdentity,
) -> None:
    if metadata.get("id") != 15205417 or metadata.get("doi") != "10.5281/zenodo.15205417":
        raise ValueError("persisted Zenodo metadata identifies the wrong record")
    file_metadata = zenodo_file_metadata(metadata)
    if file_metadata.get("id") != registered.provider_file_id:
        raise ValueError("persisted Zenodo file ID differs from registry")
    if file_metadata.get("key") != registered.filename:
        raise ValueError("persisted Zenodo filename differs from registry")
    if file_metadata.get("size") != registered.expected_byte_size:
        raise ValueError("persisted Zenodo byte size differs from registry")
    checksum = file_metadata.get("checksum")
    expected_provider_hash = registered.provider_hash
    if (
        not isinstance(checksum, str)
        or expected_provider_hash is None
        or checksum.removeprefix("md5:").lower() != expected_provider_hash.lower()
    ):
        raise ValueError("persisted Zenodo provider checksum differs from registry")


def _load_verified_artifact(
    data_root: Path,
    registered: RegisteredDatasetFileIdentity,
    metadata_snapshot_sha256: str,
) -> tuple[VerifiedRawArtifact, Path]:
    receipt_path = _typed_receipt_path(
        registered.source_id,
        registered.source_version,
        "acquisition",
    )
    receipt = _read_typed(data_root, receipt_path, ArtifactAcquisitionReceipt)
    if receipt.source_id != registered.source_id:
        raise ValueError("persisted acquisition receipt source ID differs from registry")
    if receipt.source_version != registered.source_version:
        raise ValueError("persisted acquisition receipt source version differs from registry")
    if receipt.sha256 != registered.expected_sha256:
        raise ValueError("persisted acquisition receipt SHA-256 differs from registry")
    if receipt.byte_size != registered.expected_byte_size:
        raise ValueError("persisted acquisition receipt byte size differs from registry")
    if receipt.original_filename != registered.filename:
        raise ValueError("persisted acquisition receipt filename differs from registry")
    if receipt.media_type != registered.media_type:
        raise ValueError("persisted acquisition receipt media type differs from registry")
    if receipt.representation is not registered.representation:
        raise ValueError("persisted acquisition receipt representation differs from registry")
    if receipt.provider_file_id != registered.provider_file_id:
        raise ValueError("persisted acquisition receipt provider file ID differs from registry")
    if receipt.metadata_snapshot_sha256 != metadata_snapshot_sha256:
        raise ValueError("persisted acquisition receipt metadata snapshot differs from registry")
    if receipt.storage_relative_path != _raw_relative_path(registered):
        raise ValueError("persisted acquisition receipt storage path differs from registry")
    if registered.provider_hash is not None:
        if receipt.provider_hash != registered.provider_hash:
            raise ValueError("persisted acquisition receipt provider hash differs from registry")
        if (
            registered.provider_hash_algorithm is None
            or receipt.provider_hash_algorithm != registered.provider_hash_algorithm
        ):
            raise ValueError("persisted acquisition receipt provider hash algorithm differs")
    raw_path = _raw_path(data_root, registered)
    actual_sha256, actual_byte_size = file_digest_and_size(raw_path)
    if (
        actual_sha256 != registered.expected_sha256
        or actual_byte_size != registered.expected_byte_size
    ):
        raise ValueError("persisted raw object differs from the registered file identity")
    artifact = VerifiedRawArtifact(
        artifact_id=InstanceIdentifier("artifact", registered.expected_sha256),
        sha256=receipt.sha256,
        byte_size=receipt.byte_size,
        media_type=receipt.media_type,
        relative_path=receipt.storage_relative_path,
        acquisition_receipt=receipt,
        representation=receipt.representation,
    )
    if artifact.sha256 != actual_sha256:
        raise ValueError("verified artifact digest differs from persisted raw bytes")
    return artifact, raw_path


def _load_saved_original_verification(
    data_root: Path,
    registered: RegisteredDatasetFileIdentity,
    metadata_snapshot_sha256: str,
) -> SavedOriginalVerificationReceipt:
    receipt_path = _typed_receipt_path(
        registered.source_id,
        registered.source_version,
        "saved-original-verification",
    )
    receipt = _read_typed(data_root, receipt_path, SavedOriginalVerificationReceipt)
    if receipt.source_id != registered.source_id:
        raise ValueError("saved-original receipt source ID differs from registry")
    if receipt.source_version != registered.source_version:
        raise ValueError("saved-original receipt source version differs from registry")
    if receipt.provider_file_id != registered.provider_file_id:
        raise ValueError("saved-original receipt provider file ID differs from registry")
    if receipt.file_persistent_identifier != registered.file_persistent_identifier:
        raise ValueError("saved-original receipt file PID differs from registry")
    if receipt.provider_hash != registered.provider_hash:
        raise ValueError("saved-original receipt provider hash differs from registry")
    if receipt.provider_hash_algorithm.lower() != "md5":
        raise ValueError("saved-original receipt provider hash algorithm is not md5")
    if receipt.metadata_snapshot_sha256 != metadata_snapshot_sha256:
        raise ValueError("saved-original receipt metadata snapshot differs from registry")
    entry = registry_file_entries(load_dataset_registry(SOURCE_A_ID))[0]
    if receipt.observed_byte_size != entry.get("saved_original_byte_size"):
        raise ValueError("saved-original receipt byte size differs from registry")
    if receipt.representation is not FileRepresentation.SAVED_ORIGINAL:
        raise ValueError("saved-original receipt representation is not SAVED_ORIGINAL")
    if not isinstance(receipt, SavedOriginalVerificationReceipt):
        raise ValueError("persisted saved-original receipt has the wrong type")
    return receipt


def _records_factory(
    raw_path: Path,
    *,
    raw_sha256: str,
    schema_sha256: str,
    population_decision: Any,
    source_decision: Any,
) -> Iterator[CanonicalEmpiricalRecord]:
    return map_source_a_records(
        raw_path,
        raw_artifact_sha256=raw_sha256,
        schema_sha256=schema_sha256,
        acquisition_receipt_id=f"acquisition:{raw_sha256}",
        population_decision=population_decision,
        source_decision=source_decision,
    )


def _variable_payload(identity: Any) -> dict[str, object]:
    payload = canonical_data(identity)
    if not isinstance(payload, dict):
        raise ValueError("source variable identity did not serialize to an object")
    payload.pop("__type__", None)
    return payload


def _source_a_qualification(
    *,
    artifact_sha256: str,
    variable_registry: Any,
) -> DatasetQualificationReceipt:
    population_decision, source_decision = source_a_population_and_source_decisions()
    return qualify_dataset(
        SOURCE_A_SOURCE,
        SOURCE_A_VERSION,
        population_decision.population,
        source_decision.source,
        artifact_sha256=artifact_sha256,
        license_identity=dataset_license_identity(load_dataset_registry(SOURCE_A_ID)),
        variable_identities=tuple(entry.identity for entry in variable_registry.entries),
        football_mapping_status=VariableResolutionStatus.RESOLVED,
        evidence=(SOURCE_A_LANDING_PAGE, "https://doi.org/10.3390/jfmk10040385"),
    )


def _source_a_report_documents(
    *,
    artifact: VerifiedRawArtifact,
    saved_original_verification: SavedOriginalVerificationReceipt,
    schema: Any,
    variable_registry: Any,
    population_decision: Any,
    source_decision: Any,
    canonical_receipt: Any,
    metadata_snapshot_sha256: str,
) -> dict[str, dict[str, object]]:
    conflicts = source_a_metadata_conflicts(
        verified_row_count=schema.row_count,
        verified_distinct_athletes=schema.distinct_athlete_ids,
        verified_distinct_game_dates=schema.distinct_game_dates,
        verified_byte_size=artifact.byte_size,
        verified_provider_md5=saved_original_verification.observed_md5,
    )
    conflict_payload = [
        {
            "field": conflict.field,
            "claims": [
                {
                    "value": claim.value,
                    "source": claim.assertion_source_uri,
                    "label": claim.claim_label,
                }
                for claim in conflict.claims
            ],
            "verified_file_fact": conflict.verified_file_fact,
            "resolution": conflict.resolution,
        }
        for conflict in conflicts
    ]
    representation = source_a_representation_audit(
        verified_archival_sha256=artifact.sha256,
        verified_archival_byte_size=artifact.byte_size,
        saved_original_verification=saved_original_verification,
        registered_file_identity=SOURCE_A_REGISTERED_FILE,
    )
    schema_payload = {
        "source_id": schema.source_id,
        "source_version": schema.source_version,
        "raw_artifact_sha256": schema.raw_artifact_sha256,
        "original_filename": schema.original_filename,
        "rows": schema.row_count,
        "columns": schema.column_count,
        "header": list(schema.columns),
        "distinct_athlete_ids": schema.distinct_athlete_ids,
        "distinct_game_dates": schema.distinct_game_dates,
        "duplicate_raw_rows": schema.duplicate_raw_rows,
        "candidate_natural_key_duplicates": schema.candidate_natural_key_duplicates,
        "missing_counts": {entry.key: entry.value for entry in schema.missing_counts},
        "schema_sha256": schema.schema_sha256,
    }
    qualification_payload = {
        "source_id": SOURCE_A_ID,
        "source_version": SOURCE_A_VERSION.repository_version,
        "source_persistent_identifier": SOURCE_A_SOURCE.persistent_identifier,
        "population_decision_id": population_decision.decision_id.stable_id,
        "source_decision_id": source_decision.decision_id.stable_id,
        "candidate_role": "CANONICAL_EMPIRICAL_TARGET",
        "population_status": population_decision.status.value,
        "population_clauses": {
            clause.dimension.value: clause.observed_value for clause in population_decision.clauses
        },
        "population_evidence": [
            {
                "dimension": binding.dimension.value,
                "value": binding.value,
                "source": binding.evidence_reference.reference_ids[0]
                if binding.evidence_reference is not None
                else None,
                "note": binding.source_note,
            }
            for binding in population_decision.population.evidence_bindings
        ],
        "source_status": source_decision.status.value,
        "source_requirements": {
            requirement.requirement.value: requirement.status.value
            for requirement in source_decision.requirements
        },
        "license": "CC-BY-NC-4.0",
        "model_training_use": "NOT_AUTHORIZED_BY_RES63",
        "football_mapping": (
            "PASS_FOR_SOURCE_SUPPORTED_ATHLETE_DATE_SEASON_COMPETITION_POSITION_CONTEXT"
        ),
        "season_mapping": "2020-2024_FROM_GAMEDATE_YEAR",
        "lineage": "PASS",
        "mapping_version": SOURCE_A_MAPPING_VERSION,
    }
    artifact_payload = {
        "source_id": SOURCE_A_ID,
        "source_version": SOURCE_A_VERSION.repository_version,
        "dataset_persistent_identifier": SOURCE_A_SOURCE.persistent_identifier,
        "file_id": SOURCE_A_REGISTERED_FILE.provider_file_id,
        "file_persistent_identifier": SOURCE_A_REGISTERED_FILE.file_persistent_identifier,
        "representation": SOURCE_A_REGISTERED_FILE.representation.value,
        "original_filename": SOURCE_A_REGISTERED_FILE.filename,
        "media_type": SOURCE_A_REGISTERED_FILE.media_type,
        "raw_artifact_sha256": artifact.sha256,
        "byte_size": artifact.byte_size,
        "content_addressed_relative_path": artifact.relative_path,
        "provider_hash": SOURCE_A_REGISTERED_FILE.provider_hash,
        "provider_hash_algorithm": SOURCE_A_REGISTERED_FILE.provider_hash_algorithm,
        "provider_hash_role": SOURCE_A_REGISTERED_FILE.provider_hash_representation.value
        if SOURCE_A_REGISTERED_FILE.provider_hash_representation is not None
        else None,
        "provider_hash_verified": representation["provider_hash_verified"],
        "metadata_snapshot_sha256": metadata_snapshot_sha256,
        "canonical_artifact_relative_path": canonical_receipt.relative_path,
        "canonical_artifact_sha256": canonical_receipt.canonical_artifact_sha256,
        "canonical_record_count": canonical_receipt.canonical_record_count,
        "mapping_version": canonical_receipt.mapping_version,
        "variable_registry_sha256": canonical_receipt.variable_registry_sha256,
        "variable_registry_relative_path": canonical_receipt.variable_registry_relative_path,
        "bytes_replay": "PASS",
        "canonical_replay": "PASS",
        "representation_audit": representation,
    }
    variable_payload = {
        "source_id": SOURCE_A_ID,
        "source_version": SOURCE_A_VERSION.repository_version,
        "variable_registry_sha256": variable_registry.sha256,
        "variables": [
            {"variable_id": entry.variable_id, **_variable_payload(entry.identity)}
            for entry in variable_registry.entries
        ],
    }
    metadata_payload = {
        "source_id": SOURCE_A_ID,
        "source_version": SOURCE_A_VERSION.repository_version,
        "conflict_count": len(conflict_payload),
        "conflict_kind": "CLAIM_CONFLICT",
        "conflicts": conflict_payload,
        "distinct_source_athlete_ids": schema.distinct_athlete_ids,
        "distinct_game_date_values": schema.distinct_game_dates,
        "verified_official_match_count": None,
        "representation_audit": representation,
        "byte_authority": "DYNAMISLM_SHA256",
        "provider_claims_are_not_file_truth": True,
    }
    return {
        "source-a-artifact-receipt.json": artifact_payload,
        "source-a-metadata-conflicts.json": metadata_payload,
        "source-a-qualification.json": qualification_payload,
        "source-a-schema.json": schema_payload,
        "source-a-variable-identities.json": variable_payload,
    }


def _source_b_reports(
    *,
    artifact: VerifiedRawArtifact,
    schema: WorkbookSchema,
) -> dict[str, dict[str, object]]:
    sheet = next((item for item in schema.sheets if item.sheet_name == "Limpio"), None)
    if sheet is None:
        raise ValueError("Source B persisted workbook has no Limpio worksheet")
    quarantine = source_b_quarantine(artifact.sha256)
    report: dict[str, object] = {
        "source_id": SOURCE_B_ID,
        "source_version": SOURCE_B_VERSION.repository_version,
        "candidate_role": "CANONICAL_EMPIRICAL_TARGET",
        "status": "QUARANTINED",
        "population": "UNRESOLVED",
        "variable_identity": "UNRESOLVED_FOR_PROMOTION",
        "football_mapping": "UNRESOLVED_FOR_PROMOTION",
        "lineage": "RAW_BYTES_VERIFIED_BUT_NOT_PROMOTED",
        "reason_codes": list(quarantine.reason_codes),
        "missing_information": list(quarantine.missing_information),
        "doi": "10.17632/spkmxfsmhv.1",
        "license": "CC-BY-4.0",
        "model_training_use": "NOT_AUTHORIZED_BY_RES63",
    }
    schema_report: dict[str, object] = {
        "source_id": schema.source_id,
        "source_version": schema.source_version,
        "raw_artifact_sha256": schema.raw_artifact_sha256,
        "worksheet": sheet.sheet_name,
        "rows": sheet.row_count,
        "columns": sheet.column_count,
        "distinct_athlete_ids": sheet.distinct_athlete_ids,
        "distinct_match_or_date_ids": sheet.distinct_match_or_date_ids,
        "missing_values_preserved": True,
        "missing_counts": (
            f"all {sheet.column_count} columns: 0"
            if all(entry.value == 0 for entry in sheet.missing_counts)
            else {entry.key: entry.value for entry in sheet.missing_counts}
        ),
        "headers": list(sheet.headers),
        "schema_sha256": schema.schema_sha256,
    }
    return {
        "source-b-qualification.json": report,
        "source-b-schema.json": schema_report,
    }


def _source_c_reports(
    *,
    artifact: VerifiedRawArtifact,
    schema: WorkbookSchema,
) -> dict[str, dict[str, object]]:
    granularity = classify_source_c_granularity(schema)
    if granularity != "TEAM":
        raise ValueError(f"Source C replay granularity is {granularity}, expected TEAM")
    quarantine = source_c_quarantine(schema, artifact.sha256)
    return {
        "source-c-quarantine.json": {
            "source_id": quarantine.source_id,
            "source_version": quarantine.source_version,
            "doi": "10.17632/xmzc44rptr.1",
            "status": "QUARANTINED",
            "granularity": granularity,
            "raw_artifact_sha256": quarantine.artifact_sha256,
            "reason_codes": list(quarantine.reason_codes),
            "missing_information": list(quarantine.missing_information),
            "schema_sha256": schema.schema_sha256,
            "model_training_use": "NOT_AUTHORIZED_BY_RES63",
        }
    }


def _source_d_reports(
    *,
    artifact: VerifiedRawArtifact,
    archive_inventory: dict[str, object],
) -> dict[str, dict[str, object]]:
    quarantine = source_d_quarantine(artifact.sha256)
    return {
        "source-d-quarantine.json": {
            "source_id": quarantine.source_id,
            "source_version": quarantine.source_version,
            "doi": "10.5281/zenodo.15205417",
            "status": "QUARANTINED",
            "provenance": "UNRESOLVED",
            "raw_artifact_sha256": quarantine.artifact_sha256,
            "provider_hash": SOURCE_D_REGISTERED_FILE.provider_hash,
            "provider_hash_algorithm": SOURCE_D_REGISTERED_FILE.provider_hash_algorithm,
            "reason_codes": list(quarantine.reason_codes),
            "missing_information": list(quarantine.missing_information),
            "archive_member_count": archive_inventory["member_count"],
            "model_training_use": "NOT_AUTHORIZED_BY_RES63",
        }
    }


def _write_reports(report_dir: Path, documents: dict[str, dict[str, object]]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (report_dir / name).write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _compare_typed_quarantine(
    data_root: Path,
    source_id: str,
    expected: QuarantineReceipt,
) -> None:
    path = f"quarantine/{_safe_slug(source_id)}.json"
    persisted = _read_typed(data_root, path, QuarantineReceipt)
    if persisted != expected:
        raise ValueError(f"persisted quarantine state diverges: {source_id}")


def replay(data_root: Path, *, report_dir: Path | None, verify: bool) -> dict[str, object]:
    resolved_root = resolve_data_root(data_root, repository_root=_REPOSITORY_ROOT)

    source_a_registry = load_dataset_registry(SOURCE_A_ID)
    source_a_metadata_sha256 = source_a_registry.get("metadata_snapshot_sha256")
    if not isinstance(source_a_metadata_sha256, str):
        raise ValueError("Source A registry lacks metadata_snapshot_sha256")
    source_a_metadata = _read_metadata_snapshot(
        resolved_root,
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        expected_sha256=source_a_metadata_sha256,
    )
    source_a_file_metadata(source_a_metadata)
    source_a_artifact, source_a_raw_path = _load_verified_artifact(
        resolved_root,
        SOURCE_A_REGISTERED_FILE,
        source_a_metadata_sha256,
    )
    representation_registry = source_a_registry.get("representation_audit")
    expected_saved_original_receipt_path = _typed_receipt_path(
        SOURCE_A_ID,
        SOURCE_A_VERSION.repository_version,
        "saved-original-verification",
    )
    if (
        not isinstance(representation_registry, dict)
        or representation_registry.get("provider_verification_receipt")
        != expected_saved_original_receipt_path
    ):
        raise ValueError("Source A registry does not bind its provider verification receipt")
    saved_original = _load_saved_original_verification(
        resolved_root,
        SOURCE_A_REGISTERED_FILE,
        source_a_metadata_sha256,
    )
    representation = source_a_representation_audit(
        verified_archival_sha256=source_a_artifact.sha256,
        verified_archival_byte_size=source_a_artifact.byte_size,
        saved_original_verification=saved_original,
        registered_file_identity=SOURCE_A_REGISTERED_FILE,
    )
    if representation["provider_hash_verified"] is not True:
        raise ValueError("SOURCE_A_PROVIDER_HASH_VERIFIED failed from persisted evidence")
    source_a_schema = inspect_source_a(source_a_raw_path, SOURCE_A_REGISTERED_FILE.expected_sha256)
    source_a_variables = source_a_variable_registry(source_a_schema.columns)
    population_decision, source_decision = source_a_population_and_source_decisions()
    qualification = _source_a_qualification(
        artifact_sha256=source_a_artifact.sha256,
        variable_registry=source_a_variables,
    )
    persisted_qualification = _read_typed(
        resolved_root,
        "receipts/unifesp-brazil-serie-a-v1-qualification.json",
        DatasetQualificationReceipt,
    )
    if persisted_qualification != qualification:
        raise ValueError(
            "persisted Source A qualification diverges from deterministic qualification"
        )

    def source_a_records() -> Iterator[CanonicalEmpiricalRecord]:
        return _records_factory(
            source_a_raw_path,
            raw_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
            schema_sha256=source_a_schema.schema_sha256,
            population_decision=population_decision,
            source_decision=source_decision,
        )

    validation = validate_canonical_records(
        source_a_records(),
        variable_registry=source_a_variables,
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
        mapping_version=SOURCE_A_MAPPING_VERSION,
    )
    canonical_receipt = write_canonical_jsonl(
        source_a_records(),
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
        mapping_version=SOURCE_A_MAPPING_VERSION,
        variable_registry=source_a_variables,
        metadata_snapshot_sha256=source_a_metadata_sha256,
        data_root=resolved_root,
        repository_root=_REPOSITORY_ROOT,
    )
    if validation.canonical_artifact_sha256 != canonical_receipt.canonical_artifact_sha256:
        raise ValueError("canonical replay validation and writer digests differ")
    if validation.canonical_record_count != canonical_receipt.canonical_record_count:
        raise ValueError("canonical replay validation and writer counts differ")
    canonical_registry = source_a_registry.get("canonical_artifact")
    if not isinstance(canonical_registry, dict):
        raise ValueError("Source A registry lacks canonical_artifact identity")
    canonical_checks = {
        "sha256": canonical_receipt.canonical_artifact_sha256,
        "record_count": canonical_receipt.canonical_record_count,
        "mapping_version": canonical_receipt.mapping_version,
        "variable_registry_sha256": canonical_receipt.variable_registry_sha256,
        "relative_path": canonical_receipt.relative_path,
        "variable_registry_relative_path": canonical_receipt.variable_registry_relative_path,
    }
    expected_canonical_checks = {
        "sha256": canonical_registry.get("sha256"),
        "record_count": canonical_registry.get("record_count"),
        "mapping_version": canonical_registry.get("mapping_version"),
        "variable_registry_sha256": canonical_registry.get("variable_registry_sha256"),
        "relative_path": canonical_registry.get("relative_path"),
        "variable_registry_relative_path": canonical_registry.get(
            "variable_registry_relative_path"
        ),
    }
    if canonical_checks != expected_canonical_checks:
        raise ValueError("Source A registry canonical_artifact block diverges from replay")
    verify_canonical_artifact(
        resolved_root / canonical_receipt.relative_path,
        expected_sha256=canonical_receipt.canonical_artifact_sha256,
        expected_record_count=canonical_receipt.canonical_record_count,
    )

    source_b_registry = load_dataset_registry(SOURCE_B_ID)
    source_b_metadata_sha256 = source_b_registry.get("metadata_snapshot_sha256")
    if not isinstance(source_b_metadata_sha256, str):
        raise ValueError("Source B registry lacks metadata_snapshot_sha256")
    source_b_metadata = _read_metadata_snapshot(
        resolved_root,
        source_id=SOURCE_B_ID,
        source_version="1",
        expected_sha256=source_b_metadata_sha256,
    )
    _verify_persisted_metadata_file_identity(source_b_metadata, SOURCE_B_REGISTERED_FILE)
    source_b_artifact, source_b_raw_path = _load_verified_artifact(
        resolved_root,
        SOURCE_B_REGISTERED_FILE,
        source_b_metadata_sha256,
    )
    source_b_schema = inspect_workbook(
        source_b_raw_path,
        source_id=SOURCE_B_ID,
        source_version="1",
        raw_artifact_sha256=source_b_artifact.sha256,
    )
    _compare_typed_quarantine(
        resolved_root,
        SOURCE_B_ID,
        source_b_quarantine(source_b_artifact.sha256),
    )

    source_c_registry = load_dataset_registry(SOURCE_C_ID)
    source_c_metadata_sha256 = source_c_registry.get("metadata_snapshot_sha256")
    if not isinstance(source_c_metadata_sha256, str):
        raise ValueError("Source C registry lacks metadata_snapshot_sha256")
    source_c_metadata = _read_metadata_snapshot(
        resolved_root,
        source_id=SOURCE_C_ID,
        source_version="1",
        expected_sha256=source_c_metadata_sha256,
    )
    _verify_persisted_metadata_file_identity(source_c_metadata, SOURCE_C_REGISTERED_FILE)
    source_c_artifact, source_c_raw_path = _load_verified_artifact(
        resolved_root,
        SOURCE_C_REGISTERED_FILE,
        source_c_metadata_sha256,
    )
    source_c_schema = inspect_source_c(source_c_raw_path, source_c_artifact.sha256)
    _compare_typed_quarantine(
        resolved_root,
        SOURCE_C_ID,
        source_c_quarantine(source_c_schema, source_c_artifact.sha256),
    )

    source_d_registry = load_dataset_registry(SOURCE_D_ID)
    source_d_metadata_sha256 = source_d_registry.get("metadata_snapshot_sha256")
    if not isinstance(source_d_metadata_sha256, str):
        raise ValueError("Source D registry lacks metadata_snapshot_sha256")
    source_d_metadata = _read_metadata_snapshot(
        resolved_root,
        source_id=SOURCE_D_ID,
        source_version="1.0",
        expected_sha256=source_d_metadata_sha256,
    )
    _verify_persisted_zenodo_metadata(source_d_metadata, SOURCE_D_REGISTERED_FILE)
    source_d_artifact, source_d_raw_path = _load_verified_artifact(
        resolved_root,
        SOURCE_D_REGISTERED_FILE,
        source_d_metadata_sha256,
    )
    source_d_archive_inventory = inspect_source_d_archive(
        source_d_raw_path,
        raw_artifact_sha256=source_d_artifact.sha256,
    )
    _compare_typed_quarantine(
        resolved_root,
        SOURCE_D_ID,
        source_d_quarantine(source_d_artifact.sha256),
    )

    documents = {
        **_source_a_report_documents(
            artifact=source_a_artifact,
            saved_original_verification=saved_original,
            schema=source_a_schema,
            variable_registry=source_a_variables,
            population_decision=population_decision,
            source_decision=source_decision,
            canonical_receipt=canonical_receipt,
            metadata_snapshot_sha256=source_a_metadata_sha256,
        ),
        **_source_b_reports(artifact=source_b_artifact, schema=source_b_schema),
        **_source_c_reports(artifact=source_c_artifact, schema=source_c_schema),
        **_source_d_reports(
            artifact=source_d_artifact,
            archive_inventory=source_d_archive_inventory,
        ),
    }
    if tuple(documents) != _REPORT_NAMES:
        raise ValueError("RES-63 report family is incomplete or unstable")
    if verify:
        with tempfile.TemporaryDirectory(prefix="res63-reports-") as temporary:
            generated_dir = Path(temporary)
            _write_reports(generated_dir, documents)
            expected_dir = _REPOSITORY_ROOT / "reports" / "res63"
            committed_report_names = tuple(
                sorted(path.name for path in expected_dir.glob("*.json"))
            )
            if set(committed_report_names) != set(_REPORT_NAMES):
                raise ValueError("committed RES-63 report family differs from replay scope")
            for name in _REPORT_NAMES:
                if (expected_dir / name).read_bytes() != (generated_dir / name).read_bytes():
                    raise ValueError(f"REPORT_REPLAY divergence: {name}")
    if report_dir is not None:
        _write_reports(report_dir, documents)
    inventory = data_root_inventory(resolved_root)
    return {
        "SOURCE_A_CANONICAL_REPLAY": "PASS",
        "SOURCE_A_PROVIDER_HASH_VERIFIED": "PASS",
        "SOURCE_A_SAVED_ORIGINAL_STORED": "NO",
        "REPORT_REPLAY_SCOPE": "ALL_COMMITTED_RES63_REPORTS",
        "REPORT_REPLAY": "PASS" if verify else "NOT_REQUESTED",
        "canonical_sha256": canonical_receipt.canonical_artifact_sha256,
        "canonical_record_count": canonical_receipt.canonical_record_count,
        "saved_original_byte_size": saved_original.observed_byte_size,
        "saved_original_sha256": saved_original.observed_sha256,
        "saved_original_provider_md5": saved_original.observed_md5,
        "variable_registry_sha256": source_a_variables.sha256,
        **inventory,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=(SOURCE_A_ID,))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = replay(args.data_root, report_dir=args.report_dir, verify=args.verify)
    except (OSError, ValueError) as exc:
        print("REPORT_REPLAY=FAIL")
        print("SOURCE_A_PROVIDER_HASH_VERIFIED=FAIL")
        print(f"RES63_REPLAY=FAIL: {exc}", file=sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
