"""Source D metadata/acquisition helpers and provenance quarantine."""

from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from dynamislm.ingestion.acquisition import acquire_url, capture_metadata_snapshot
from dynamislm.ingestion.contracts import (
    FileRepresentation,
    QuarantineReceipt,
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

SOURCE_D_ID = "zenodo-ekstraklasa-training-adaptation"
SOURCE_D_DOI = "10.5281/zenodo.15205417"
SOURCE_D_PROVIDER = "Zenodo"
SOURCE_D_LANDING_PAGE = "https://zenodo.org/records/15205417"
SOURCE_D_MAPPING_VERSION = "zenodo-ekstraklasa-training-adaptation-mapping@1.0.0"
SOURCE_D_FILE_NAME = "StudyPackage_Training_Adaptation.zip"

SOURCE_D_REGISTRY_DOCUMENT = load_dataset_registry(SOURCE_D_ID)
SOURCE_D_REGISTERED_FILE = registered_dataset_file_identity(SOURCE_D_REGISTRY_DOCUMENT)

SOURCE_D_SOURCE = dataset_source_identity(SOURCE_D_REGISTRY_DOCUMENT)
SOURCE_D_VERSION = dataset_version_identity(SOURCE_D_REGISTRY_DOCUMENT)
SOURCE_D_LICENSE = dataset_license_identity(SOURCE_D_REGISTRY_DOCUMENT)


def fetch_zenodo_metadata(record_id: int = 15205417) -> dict[str, Any]:
    """Fetch official Zenodo record metadata without credentials."""

    request = urllib.request.Request(
        f"https://zenodo.org/api/records/{record_id}",
        headers={"User-Agent": "DynamisLM-RES63/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Zenodo record metadata must be an object")
    return payload


def zenodo_file_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    files = metadata.get("files")
    if not isinstance(files, list):
        raise ValueError("Zenodo record metadata lacks a file list")
    for entry in files:
        if isinstance(entry, dict) and entry.get("key") == SOURCE_D_FILE_NAME:
            return entry
    raise ValueError(f"Zenodo Source D file not found: {SOURCE_D_FILE_NAME}")


def acquire_source_d(
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> Any:
    """Acquire the official Zenodo package, retaining provider MD5 separately."""

    metadata = fetch_zenodo_metadata()
    snapshot_sha256 = capture_metadata_snapshot(
        SOURCE_D_SOURCE,
        SOURCE_D_VERSION,
        metadata,
        data_root=data_root,
        repository_root=repository_root,
    )
    file_metadata = zenodo_file_metadata(metadata)
    links = file_metadata.get("links")
    if not isinstance(links, dict):
        raise ValueError("Zenodo Source D file metadata lacks download links")
    download_url = links.get("self") or links.get("content")
    size = file_metadata.get("size")
    checksum = file_metadata.get("checksum")
    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        raise ValueError("Zenodo Source D lacks a public HTTPS download URL")
    if isinstance(size, bool) or not isinstance(size, int):
        raise ValueError("Zenodo Source D lacks a byte size")
    provider_hash = str(checksum).removeprefix("md5:") if checksum is not None else None
    verify_live_provider_file_observation(
        SOURCE_D_REGISTERED_FILE,
        provider_hash=provider_hash,
        provider_hash_algorithm="md5" if provider_hash is not None else None,
        provider_byte_size=size,
        provider_file_id=file_metadata.get("id", file_metadata.get("file_id")),
    )
    return acquire_url(
        SOURCE_D_SOURCE,
        SOURCE_D_VERSION,
        download_url,
        registered_file_identity=SOURCE_D_REGISTERED_FILE,
        representation=FileRepresentation.PROVIDER_FILE,
        provider_file_id=file_metadata.get("id", file_metadata.get("file_id")),
        provider_hash=provider_hash,
        provider_hash_algorithm="md5" if provider_hash is not None else None,
        metadata_snapshot_sha256=snapshot_sha256,
        original_filename=SOURCE_D_FILE_NAME,
        media_type="application/zip",
        data_root=data_root,
        repository_root=repository_root,
    )


def source_d_quarantine(artifact_sha256: str | None = None) -> QuarantineReceipt:
    """Keep Source D out of canonical promotion pending provenance audit."""

    return QuarantineReceipt(
        source_id=SOURCE_D_ID,
        source_version=SOURCE_D_VERSION.repository_version,
        failed_stage="QUARANTINE_PROVENANCE_AUDIT",
        reason_codes=(
            "UNRESOLVED_PUBLICATION_PROVENANCE",
            "UNRESOLVED_FIRST_TEAM_STATUS",
        ),
        missing_information=(
            "independent manuscript/publication provenance for the exact package contents",
            "explicit evidence linking every retained athlete row to a senior first-team "
            "top-domestic-division cohort",
            "raw-vs-derived status for jump-test, GPS, strength, HRV, and RPE fields",
        ),
        evidence=(SOURCE_D_LANDING_PAGE,),
        artifact_sha256=artifact_sha256,
        affected_variables=(
            "jump-test, GPS, strength, HRV, RPE, DOMS, and all derived package fields",
        ),
        requirements_for_requalification=(
            "verify archive inventory and provider checksums",
            "link package files to the published manuscript and protocols",
            "separate raw observations from provider/model-derived outputs",
            "rerun RES-60 population qualification before any promotion",
        ),
    )


def inspect_source_d_archive(
    path: Path,
    *,
    raw_artifact_sha256: str,
) -> dict[str, object]:
    """Inspect the registered archive inventory from the verified ZIP bytes."""

    actual_digest, _ = file_digest_and_size(path)
    if actual_digest != raw_artifact_sha256:
        raise ValueError("Source D archive bytes do not match the verified artifact digest")
    expected_inventory = SOURCE_D_REGISTRY_DOCUMENT.get("archive_inventory")
    if not isinstance(expected_inventory, dict):
        raise ValueError("Source D registry lacks archive inventory")
    expected_data_member = expected_inventory.get("data_member")
    expected_readme_member = expected_inventory.get("README_member")
    if not isinstance(expected_data_member, str) or not isinstance(expected_readme_member, str):
        raise ValueError("Source D archive inventory lacks named members")
    try:
        with zipfile.ZipFile(path) as archive:
            names = tuple(info.filename for info in archive.infolist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("Source D verified artifact is not a readable ZIP archive") from exc
    inventory: dict[str, object] = {
        "member_count": len(names),
        "data_member": expected_data_member if expected_data_member in names else None,
        "README_member": expected_readme_member if expected_readme_member in names else None,
        "figures_present": any(name.lower().endswith(".png") for name in names),
    }
    if inventory["member_count"] != expected_inventory.get("member_count"):
        raise ValueError("Source D archive member count differs from the registry")
    if inventory["data_member"] is None or inventory["README_member"] is None:
        raise ValueError("Source D archive inventory is missing a registered member")
    if inventory["figures_present"] is not expected_inventory.get("figures_present"):
        raise ValueError("Source D archive figure inventory differs from the registry")
    return inventory


__all__ = [
    "SOURCE_D_DOI",
    "SOURCE_D_FILE_NAME",
    "SOURCE_D_ID",
    "SOURCE_D_LANDING_PAGE",
    "SOURCE_D_LICENSE",
    "SOURCE_D_MAPPING_VERSION",
    "SOURCE_D_PROVIDER",
    "SOURCE_D_SOURCE",
    "SOURCE_D_VERSION",
    "acquire_source_d",
    "fetch_zenodo_metadata",
    "inspect_source_d_archive",
    "source_d_quarantine",
    "zenodo_file_metadata",
]
