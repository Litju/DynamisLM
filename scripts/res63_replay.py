#!/usr/bin/env python3
"""Offline deterministic replay and report regeneration for Source A RES-63."""

from __future__ import annotations

import argparse
import datetime as datetime_module
import json
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dynamislm.ingestion.acquisition import verify_registered_artifact
from dynamislm.ingestion.adapters.unifesp_serie_a import (
    SOURCE_A_ID,
    SOURCE_A_MAPPING_VERSION,
    SOURCE_A_REGISTERED_FILE,
    SOURCE_A_SOURCE,
    SOURCE_A_VERSION,
    inspect_source_a,
    map_source_a_records,
    source_a_metadata_conflicts,
    source_a_population_and_source_decisions,
    source_a_representation_audit,
    source_a_variable_registry,
)
from dynamislm.ingestion.contracts import (
    ArtifactAcquisitionReceipt,
    CanonicalEmpiricalRecord,
    RegisteredDatasetFileIdentity,
    VerifiedRawArtifact,
)
from dynamislm.ingestion.promotion import (
    validate_canonical_records,
    write_canonical_jsonl,
)
from dynamislm.ingestion.registry import load_dataset_registry, registry_file_entries
from dynamislm.ingestion.storage import (
    data_root_inventory,
    file_digest_and_size,
    resolve_data_root,
    verify_file,
)
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.serialization import canonical_data

_REPORT_NAMES = (
    "source-a-artifact-receipt.json",
    "source-a-metadata-conflicts.json",
    "source-a-qualification.json",
    "source-a-schema.json",
    "source-a-variable-identities.json",
)


def _raw_path(data_root: Path, registered: RegisteredDatasetFileIdentity) -> Path:
    digest = registered.expected_sha256.removeprefix("sha256:")
    return data_root / "objects" / "sha256" / digest[:2] / digest


def _verified_artifact(
    data_root: Path,
    registered: RegisteredDatasetFileIdentity,
) -> VerifiedRawArtifact:
    raw_path = _raw_path(data_root, registered)
    verify_file(
        raw_path,
        expected_sha256=registered.expected_sha256,
        expected_byte_size=registered.expected_byte_size,
    )
    relative_path = (
        f"objects/sha256/{registered.expected_sha256.removeprefix('sha256:')[:2]}/"
        f"{registered.expected_sha256.removeprefix('sha256:')}"
    )
    receipt = ArtifactAcquisitionReceipt(
        source_id=registered.source_id,
        source_version=registered.source_version,
        requested_url="https://offline.invalid/registered-artifact",
        resolved_url="https://offline.invalid/registered-artifact",
        original_filename=registered.filename,
        media_type=registered.media_type,
        byte_size=registered.expected_byte_size,
        sha256=registered.expected_sha256,
        retrieved_at=datetime_module.datetime(1970, 1, 1, tzinfo=datetime_module.UTC),
        provider_hash=registered.provider_hash,
        provider_hash_algorithm=registered.provider_hash_algorithm,
        storage_relative_path=relative_path,
        representation=registered.representation,
        provider_file_id=registered.provider_file_id,
    )
    artifact = VerifiedRawArtifact(
        artifact_id=InstanceIdentifier("artifact", registered.expected_sha256),
        sha256=registered.expected_sha256,
        byte_size=registered.expected_byte_size,
        media_type=registered.media_type,
        relative_path=relative_path,
        acquisition_receipt=receipt,
        representation=registered.representation,
    )
    verify_registered_artifact(registered, artifact, data_root=data_root)
    return artifact


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


def _report_documents(
    *,
    data_root: Path,
    registered: RegisteredDatasetFileIdentity,
    artifact: VerifiedRawArtifact,
    schema: Any,
    variable_registry: Any,
    population_decision: Any,
    source_decision: Any,
    canonical_receipt: Any,
) -> dict[str, dict[str, object]]:
    raw_path = _raw_path(data_root, registered)
    _, raw_size = file_digest_and_size(raw_path)
    conflicts = source_a_metadata_conflicts(
        verified_row_count=schema.row_count,
        verified_distinct_athletes=schema.distinct_athlete_ids,
        verified_distinct_game_dates=schema.distinct_game_dates,
        verified_byte_size=raw_size,
        verified_provider_md5=registered.provider_hash or "",
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
    registry_document = load_dataset_registry(SOURCE_A_ID)
    entry = registry_file_entries(registry_document)[0]
    representation = source_a_representation_audit(
        verified_archival_sha256=artifact.sha256,
        verified_archival_byte_size=artifact.byte_size,
        verified_saved_original_md5=str(entry.get("saved_original_provider_hash", "")),
        verified_saved_original_byte_size=int(entry.get("saved_original_byte_size", 0)),
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
        "file_id": registered.provider_file_id,
        "file_persistent_identifier": registered.file_persistent_identifier,
        "representation": registered.representation.value,
        "original_filename": registered.filename,
        "media_type": registered.media_type,
        "raw_artifact_sha256": artifact.sha256,
        "byte_size": artifact.byte_size,
        "content_addressed_relative_path": artifact.relative_path,
        "provider_hash": registered.provider_hash,
        "provider_hash_algorithm": registered.provider_hash_algorithm,
        "provider_hash_role": registered.provider_hash_representation.value
        if registered.provider_hash_representation is not None
        else None,
        "provider_hash_verified": representation["provider_hash_verified"],
        "metadata_snapshot_sha256": registry_document.get("metadata_snapshot_sha256"),
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


def _write_reports(report_dir: Path, documents: dict[str, dict[str, object]]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (report_dir / name).write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def replay(data_root: Path, *, report_dir: Path | None, verify: bool) -> dict[str, object]:
    resolved_root = resolve_data_root(data_root, repository_root=Path(__file__).parents[1])
    raw_path = _raw_path(resolved_root, SOURCE_A_REGISTERED_FILE)
    artifact = _verified_artifact(resolved_root, SOURCE_A_REGISTERED_FILE)
    schema = inspect_source_a(raw_path, SOURCE_A_REGISTERED_FILE.expected_sha256)
    variable_registry = source_a_variable_registry(schema.columns)
    population_decision, source_decision = source_a_population_and_source_decisions()

    def records() -> Iterator[CanonicalEmpiricalRecord]:
        return _records_factory(
            raw_path,
            raw_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
            schema_sha256=schema.schema_sha256,
            population_decision=population_decision,
            source_decision=source_decision,
        )

    validation = validate_canonical_records(
        records(),
        variable_registry=variable_registry,
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
        mapping_version=SOURCE_A_MAPPING_VERSION,
    )
    canonical_receipt = write_canonical_jsonl(
        records(),
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=SOURCE_A_REGISTERED_FILE.expected_sha256,
        mapping_version=SOURCE_A_MAPPING_VERSION,
        variable_registry=variable_registry,
        metadata_snapshot_sha256=load_dataset_registry(SOURCE_A_ID).get("metadata_snapshot_sha256"),
        data_root=resolved_root,
        repository_root=Path(__file__).parents[1],
    )
    if validation.canonical_artifact_sha256 != canonical_receipt.canonical_artifact_sha256:
        raise ValueError("canonical replay validation and writer digests differ")
    if validation.canonical_record_count != canonical_receipt.canonical_record_count:
        raise ValueError("canonical replay validation and writer counts differ")
    documents = _report_documents(
        data_root=resolved_root,
        registered=SOURCE_A_REGISTERED_FILE,
        artifact=artifact,
        schema=schema,
        variable_registry=variable_registry,
        population_decision=population_decision,
        source_decision=source_decision,
        canonical_receipt=canonical_receipt,
    )
    if report_dir is not None:
        _write_reports(report_dir, documents)
    if verify:
        compare_dir = report_dir
        with tempfile.TemporaryDirectory(prefix="res63-reports-") as temporary:
            generated_dir = Path(temporary)
            _write_reports(generated_dir, documents)
            expected_dir = Path(__file__).parents[1] / "reports" / "res63"
            for name in _REPORT_NAMES:
                expected = (expected_dir / name).read_bytes()
                actual = (
                    (compare_dir / name).read_bytes()
                    if compare_dir
                    else (generated_dir / name).read_bytes()
                )
                if compare_dir is None:
                    actual = (generated_dir / name).read_bytes()
                if expected != actual:
                    raise ValueError(f"REPORT_REPLAY divergence: {name}")
    inventory = data_root_inventory(resolved_root)
    return {
        "SOURCE_A_CANONICAL_REPLAY": "PASS",
        "REPORT_REPLAY": "PASS" if verify else "NOT_REQUESTED",
        "canonical_sha256": canonical_receipt.canonical_artifact_sha256,
        "canonical_record_count": canonical_receipt.canonical_record_count,
        "variable_registry_sha256": variable_registry.sha256,
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
        print(f"RES63_REPLAY=FAIL: {exc}", file=sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
