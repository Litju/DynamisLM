"""Source C granularity audit for the Mendeley Turkish Super League workbook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dynamislm.ingestion.acquisition import acquire_url, capture_metadata_snapshot
from dynamislm.ingestion.adapters.mendeley_rpl import (
    fetch_mendeley_file_metadata,
    inspect_workbook,
    stable_mendeley_file_metadata,
)
from dynamislm.ingestion.contracts import (
    FileRepresentation,
    QuarantineReceipt,
    WorkbookSchema,
)
from dynamislm.ingestion.registry import (
    dataset_license_identity,
    dataset_source_identity,
    dataset_version_identity,
    load_dataset_registry,
    registered_dataset_file_identity,
    verify_live_provider_file_observation,
)
from dynamislm.ingestion.storage import file_digest_and_size

SOURCE_C_ID = "mendeley-turkish-super-league-instat-v1"
SOURCE_C_DOI = "10.17632/xmzc44rptr.1"
SOURCE_C_PROVIDER = "Mendeley Data"
SOURCE_C_LANDING_PAGE = "https://data.mendeley.com/datasets/xmzc44rptr/1"
SOURCE_C_MAPPING_VERSION = "mendeley-turkish-super-league-mapping@1.0.0"

SOURCE_C_REGISTRY_DOCUMENT = load_dataset_registry(SOURCE_C_ID)
SOURCE_C_REGISTERED_FILE = registered_dataset_file_identity(SOURCE_C_REGISTRY_DOCUMENT)

SOURCE_C_SOURCE = dataset_source_identity(SOURCE_C_REGISTRY_DOCUMENT)
SOURCE_C_VERSION = dataset_version_identity(SOURCE_C_REGISTRY_DOCUMENT)
SOURCE_C_LICENSE = dataset_license_identity(SOURCE_C_REGISTRY_DOCUMENT)


def source_c_file_metadata() -> dict[str, Any]:
    entries = fetch_mendeley_file_metadata("xmzc44rptr", version=1)
    if not entries:
        raise ValueError("Mendeley Source C has no public file metadata")
    return entries[0]


def acquire_source_c(
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> Any:
    """Acquire Source C through the same public provider route as Source B."""

    metadata = source_c_file_metadata()
    snapshot_sha256 = capture_metadata_snapshot(
        SOURCE_C_SOURCE,
        SOURCE_C_VERSION,
        stable_mendeley_file_metadata(metadata),
        data_root=data_root,
        repository_root=repository_root,
    )
    details = metadata.get("content_details")
    if not isinstance(details, dict):
        raise ValueError("Mendeley Source C file metadata lacks content_details")
    download_url = details.get("download_url")
    live_provider_sha256 = details.get("sha256_hash")
    byte_size = metadata.get("size")
    if not isinstance(download_url, str) or not isinstance(live_provider_sha256, str):
        raise ValueError("Mendeley Source C file metadata lacks public URL or SHA-256")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise ValueError("Mendeley Source C file metadata lacks byte size")
    provider_file_id = metadata.get("id", metadata.get("file_id"))
    verify_live_provider_file_observation(
        SOURCE_C_REGISTERED_FILE,
        provider_sha256=live_provider_sha256,
        provider_hash=live_provider_sha256,
        provider_hash_algorithm="sha256",
        provider_byte_size=byte_size,
        provider_file_id=provider_file_id if provider_file_id is not None else None,
    )
    return acquire_url(
        SOURCE_C_SOURCE,
        SOURCE_C_VERSION,
        download_url,
        registered_file_identity=SOURCE_C_REGISTERED_FILE,
        representation=FileRepresentation.PROVIDER_FILE,
        provider_file_id=provider_file_id if provider_file_id is not None else None,
        provider_hash=live_provider_sha256,
        provider_hash_algorithm="sha256",
        metadata_snapshot_sha256=snapshot_sha256,
        original_filename=str(metadata.get("filename", "source-c.xlsx")),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data_root=data_root,
        repository_root=repository_root,
    )


def inspect_source_c(path: Path, raw_artifact_sha256: str | None = None) -> WorkbookSchema:
    if raw_artifact_sha256 is None:
        raw_artifact_sha256, _ = file_digest_and_size(path)
    return inspect_workbook(
        path,
        source_id=SOURCE_C_ID,
        source_version=SOURCE_C_VERSION.repository_version,
        raw_artifact_sha256=raw_artifact_sha256,
    )


def classify_source_c_granularity(schema: WorkbookSchema) -> str:
    """Classify observed worksheet fields without promoting team aggregates."""

    groups: set[str] = set()
    for sheet in schema.sheets:
        headers = tuple(header.lower() for header in sheet.headers)
        has_player = any("player" in header or "athlete" in header for header in headers)
        has_team = any(
            token in header for header in headers for token in ("team", "club", "tak\u0131m")
        )
        has_match = any(token in header for header in headers for token in ("match", "game", "maç"))
        if has_player:
            groups.add("PLAYER")
        if has_team:
            groups.add("TEAM")
        if has_match:
            groups.add("MATCH")
    if not groups:
        return "UNRESOLVED"
    if "PLAYER" in groups and len(groups) == 1:
        return "PLAYER"
    if "PLAYER" in groups:
        return "MIXED"
    if "TEAM" in groups:
        return "TEAM"
    if groups == {"MATCH"}:
        return "MATCH"
    return "MIXED"


def source_c_quarantine(
    schema: WorkbookSchema | None = None,
    artifact_sha256: str | None = None,
) -> QuarantineReceipt:
    """Return the exact quarantine decision for Source C's current audit state."""

    granularity = classify_source_c_granularity(schema) if schema is not None else "UNRESOLVED"
    reasons: list[str] = []
    if granularity == "UNRESOLVED":
        reasons.append("UNRESOLVED_RECORD_GRANULARITY")
    if granularity == "TEAM":
        reasons.append("TEAM_AGGREGATE_NOT_CANONICAL_ATHLETE_RECORD")
    elif granularity == "MATCH":
        reasons.append("MATCH_LEVEL_NOT_CANONICAL_ATHLETE_RECORD")
    elif granularity == "MIXED":
        reasons.append("MIXED_OR_SUBGROUP_RECORDS_NOT_CANONICAL_ATHLETE_RECORD")
    reasons.extend(("UNRESOLVED_SEX_EVIDENCE", "UNRESOLVED_FIRST_TEAM_STATUS"))
    return QuarantineReceipt(
        source_id=SOURCE_C_ID,
        source_version=SOURCE_C_VERSION.repository_version,
        failed_stage="QUARANTINE_GRANULARITY_AUDIT",
        reason_codes=tuple(reasons),
        missing_information=(
            "proof that every retained record is an athlete-level first-team observation",
            "explicit male-sex evidence for the exact source cohort",
        ),
        evidence=(SOURCE_C_LANDING_PAGE,),
        artifact_sha256=artifact_sha256,
        affected_variables=(
            "all source variables until athlete granularity and population are resolved",
        ),
        requirements_for_requalification=(
            "retain only player-level rows if the workbook is mixed or aggregated",
            "attach exact-target population evidence and rerun RES-60 qualification",
        ),
    )


__all__ = [
    "SOURCE_C_DOI",
    "SOURCE_C_ID",
    "SOURCE_C_LANDING_PAGE",
    "SOURCE_C_LICENSE",
    "SOURCE_C_MAPPING_VERSION",
    "SOURCE_C_PROVIDER",
    "SOURCE_C_SOURCE",
    "SOURCE_C_VERSION",
    "acquire_source_c",
    "classify_source_c_granularity",
    "inspect_source_c",
    "source_c_file_metadata",
    "source_c_quarantine",
]
