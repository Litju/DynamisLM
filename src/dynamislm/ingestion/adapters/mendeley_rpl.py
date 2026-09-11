"""Source B adapter and workbook inspector for Mendeley Data RPL source."""

from __future__ import annotations

import datetime as datetime_module
import json
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openpyxl import load_workbook  # type: ignore[import-untyped]

from dynamislm.ingestion.acquisition import acquire_url, capture_metadata_snapshot
from dynamislm.ingestion.contracts import (
    FileRepresentation,
    QuarantineReceipt,
    SourceVariableIdentity,
    SourceVariableRole,
    VariableResolutionStatus,
    WorkbookSchema,
    WorkbookSheetSchema,
)
from dynamislm.ingestion.qualification import source_variable_identities
from dynamislm.ingestion.registry import (
    dataset_license_identity,
    dataset_source_identity,
    dataset_version_identity,
    load_dataset_registry,
    registered_dataset_file_identity,
    verify_live_provider_file_observation,
)
from dynamislm.ingestion.storage import file_digest_and_size
from dynamislm.measurement.identity import MetadataEntry, RegistryReference, ScientificIdentifier
from dynamislm.population.models import (
    AgeClass,
    CanonicalSource,
    CohortScope,
    CohortScopeType,
    CompetitionTier,
    DataGranularity,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationEvidenceStatus,
    PopulationIdentity,
    ProfessionalStatus,
    Sex,
    SourceDataOrigin,
    Sport,
    SquadLevel,
    SubgroupSeparability,
)
from dynamislm.population.qualification import (
    qualify_canonical_population,
    qualify_canonical_source,
)
from dynamislm.serialization import canonical_hash

SOURCE_B_ID = "mendeley-rpl-v1"
SOURCE_B_DOI = "10.17632/spkmxfsmhv.1"
SOURCE_B_PROVIDER = "Mendeley Data"
SOURCE_B_LANDING_PAGE = "https://data.mendeley.com/datasets/spkmxfsmhv/1"
SOURCE_B_FILE_NAME = "HSR + 24 GPS (Dataset).xlsx"
SOURCE_B_MAPPING_VERSION = "mendeley-rpl-mapping@1.0.0"
SOURCE_B_FILE_METADATA_URL = (
    "https://data.mendeley.com/public-api/datasets/spkmxfsmhv/files?folder_id=root&version=1"
)

SOURCE_B_REGISTRY_DOCUMENT = load_dataset_registry(SOURCE_B_ID)
SOURCE_B_REGISTERED_FILE = registered_dataset_file_identity(SOURCE_B_REGISTRY_DOCUMENT)

SOURCE_B_SOURCE = dataset_source_identity(SOURCE_B_REGISTRY_DOCUMENT)
SOURCE_B_VERSION = dataset_version_identity(SOURCE_B_REGISTRY_DOCUMENT)
SOURCE_B_LICENSE = dataset_license_identity(SOURCE_B_REGISTRY_DOCUMENT)


def fetch_mendeley_file_metadata(
    dataset_id: str,
    *,
    version: int = 1,
    opener: Any = urllib.request.urlopen,
) -> tuple[dict[str, Any], ...]:
    """Fetch the public provider file list without credentials or tokens."""

    if not dataset_id.strip():
        raise ValueError("dataset_id must not be empty")
    url = (
        f"https://data.mendeley.com/public-api/datasets/{dataset_id}/files?"
        f"folder_id=root&version={version}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "DynamisLM-RES63/1.0"})
    with opener(request, timeout=30.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Mendeley file metadata must be an array")
    entries: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Mendeley file metadata entries must be objects")
        entries.append(entry)
    return tuple(entries)


def source_b_file_metadata() -> dict[str, Any]:
    """Return the pinned public file metadata captured for Source B."""

    entries = fetch_mendeley_file_metadata("spkmxfsmhv", version=1)
    for entry in entries:
        if entry.get("filename") == SOURCE_B_FILE_NAME:
            return entry
    raise ValueError(f"Mendeley Source B file not found: {SOURCE_B_FILE_NAME}")


def stable_mendeley_file_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove provider download-expiry noise before snapshot hashing."""

    stable = dict(metadata)
    details = metadata.get("content_details")
    if isinstance(details, dict):
        stable_details = dict(details)
        stable_details.pop("download_expiry_time", None)
        stable["content_details"] = stable_details
    return stable


def acquire_source_b(
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> Any:
    """Acquire Source B through its public provider route and expected SHA-256."""

    metadata = source_b_file_metadata()
    snapshot_sha256 = capture_metadata_snapshot(
        SOURCE_B_SOURCE,
        SOURCE_B_VERSION,
        stable_mendeley_file_metadata(metadata),
        data_root=data_root,
        repository_root=repository_root,
    )
    details = metadata.get("content_details")
    if not isinstance(details, dict):
        raise ValueError("Mendeley Source B file metadata lacks content_details")
    download_url = details.get("download_url")
    live_provider_sha256 = details.get("sha256_hash")
    byte_size = metadata.get("size")
    if not all(
        isinstance(value, str) and value.strip() for value in (download_url, live_provider_sha256)
    ):
        raise ValueError("Mendeley Source B file metadata lacks public URL or SHA-256")
    assert isinstance(download_url, str)
    assert isinstance(live_provider_sha256, str)
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise ValueError("Mendeley Source B file metadata lacks byte size")
    provider_file_id = metadata.get("id", metadata.get("file_id"))
    verify_live_provider_file_observation(
        SOURCE_B_REGISTERED_FILE,
        provider_sha256=live_provider_sha256,
        provider_hash=live_provider_sha256,
        provider_hash_algorithm="sha256",
        provider_byte_size=byte_size,
        provider_file_id=provider_file_id if provider_file_id is not None else None,
    )
    return acquire_url(
        SOURCE_B_SOURCE,
        SOURCE_B_VERSION,
        download_url,
        registered_file_identity=SOURCE_B_REGISTERED_FILE,
        representation=FileRepresentation.PROVIDER_FILE,
        provider_file_id=provider_file_id if provider_file_id is not None else None,
        provider_hash=live_provider_sha256,
        provider_hash_algorithm="sha256",
        metadata_snapshot_sha256=snapshot_sha256,
        original_filename=SOURCE_B_FILE_NAME,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data_root=data_root,
        repository_root=repository_root,
    )


def _value_is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _observed_type(values: list[object]) -> str:
    present = [value for value in values if not _value_is_missing(value)]
    if not present:
        return "MISSING_ONLY"
    kinds: set[str] = set()
    for value in present:
        if isinstance(value, bool):
            kinds.add("BOOLEAN")
        elif isinstance(value, int | float):
            kinds.add("NUMERIC")
        elif isinstance(value, datetime_module.date):
            kinds.add("DATE")
        else:
            kinds.add("STRING")
    return next(iter(kinds)) if len(kinds) == 1 else "MIXED"


def _header_text(value: object, index: int) -> str:
    if value is None or not str(value).strip():
        return f"__blank_column_{index + 1}"
    return str(value)


def inspect_workbook(
    path: Path,
    *,
    source_id: str = SOURCE_B_ID,
    source_version: str = SOURCE_B_VERSION.repository_version,
    raw_artifact_sha256: str | None = None,
) -> WorkbookSchema:
    """Inspect worksheet ranges, headers, types, missingness, and field groups."""

    if raw_artifact_sha256 is None:
        raw_artifact_sha256, _ = file_digest_and_size(path)
    else:
        actual_digest, _ = file_digest_and_size(path)
        if actual_digest != "sha256:" + raw_artifact_sha256.removeprefix("sha256:").lower():
            raise ValueError("workbook bytes do not match the verified artifact digest")
    # Content-addressed objects intentionally have digest-only filenames, so
    # provide a binary stream instead of relying on an ``.xlsx`` suffix.
    workbook_bytes = path.open("rb")
    workbook = load_workbook(workbook_bytes, read_only=True, data_only=True)
    sheet_schemas: list[WorkbookSheetSchema] = []
    try:
        for worksheet in workbook.worksheets:
            rows = [tuple(row) for row in worksheet.iter_rows(values_only=True)]
            while rows and all(_value_is_missing(value) for value in rows[-1]):
                rows.pop()
            if not rows:
                continue
            width = max(len(row) for row in rows)
            normalized_rows = [row + (None,) * (width - len(row)) for row in rows]
            headers = tuple(
                _header_text(value, index) for index, value in enumerate(normalized_rows[0])
            )
            data_rows = normalized_rows[1:]
            by_column = [list(row[index] for row in data_rows) for index in range(width)]
            missing_counts = tuple(
                sum(1 for value in values if _value_is_missing(value)) for values in by_column
            )
            lower_headers = tuple(header.lower() for header in headers)
            athlete_indexes = tuple(
                index
                for index, header in enumerate(lower_headers)
                if "athlete" in header or "player" in header
            )
            match_indexes = tuple(
                index
                for index, header in enumerate(lower_headers)
                if any(token in header for token in ("match", "game", "date"))
            )
            athlete_values = {
                str(row[index]).strip()
                for row in data_rows
                for index in athlete_indexes[:1]
                if not _value_is_missing(row[index])
            }
            match_values = {
                str(row[index]).strip()
                for row in data_rows
                for index in match_indexes[:1]
                if not _value_is_missing(row[index])
            }
            field_groups: set[str] = set()
            for header in lower_headers:
                if any(token in header for token in ("gps", "distance", "hsr", "speed")):
                    field_groups.add("GPS_OR_LOCOMOTOR")
                if any(token in header for token in ("temp", "thermo", "irt")):
                    field_groups.add("THERMOGRAPHY")
            sheet_schemas.append(
                WorkbookSheetSchema(
                    sheet_name=worksheet.title,
                    headers=headers,
                    used_range=worksheet.calculate_dimension(),
                    row_count=len(data_rows),
                    column_count=width,
                    missing_counts=tuple(
                        MetadataEntry(header, count)
                        for header, count in zip(headers, missing_counts, strict=True)
                    ),
                    structural_observed_types=tuple(
                        MetadataEntry(header, _observed_type(values))
                        for header, values in zip(headers, by_column, strict=True)
                    ),
                    distinct_athlete_ids=len(athlete_values),
                    distinct_match_or_date_ids=len(match_values),
                    identified_field_groups=tuple(sorted(field_groups)),
                )
            )
    finally:
        workbook.close()
        workbook_bytes.close()
    schema_payload = {
        "source_id": source_id,
        "source_version": source_version,
        "raw_artifact_sha256": raw_artifact_sha256,
        "sheets": tuple(sheet_schemas),
    }
    return WorkbookSchema(
        source_id=source_id,
        source_version=source_version,
        raw_artifact_sha256=raw_artifact_sha256,
        sheets=tuple(sheet_schemas),
        schema_sha256=canonical_hash(schema_payload),
    )


def source_b_population() -> PopulationIdentity:
    """Represent the official evidence while leaving unreported sex unresolved."""

    evidence = RegistryReference(
        identifier=ScientificIdentifier("dynamislm", "evidence", "mendeley-rpl-paper", "1.0.0"),
        display_label="Associated Russian Premier League paper",
        reference_ids=("https://doi.org/10.3390/sports13120443",),
    )
    bindings = (
        PopulationEvidenceBinding(
            dimension=PopulationDimension.SEX,
            value=None,
            evidence_reference=None,
            status=PopulationEvidenceStatus.UNRESOLVED,
            missing_information=("explicit male-sex evidence",),
        ),
        PopulationEvidenceBinding(
            dimension=PopulationDimension.SQUAD_LEVEL,
            value=None,
            evidence_reference=None,
            status=PopulationEvidenceStatus.UNRESOLVED,
            missing_information=("explicit first-team status",),
        ),
        *tuple(
            PopulationEvidenceBinding(
                dimension=dimension,
                value=value,
                evidence_reference=evidence,
            )
            for dimension, value in (
                (PopulationDimension.AGE_CLASS, AgeClass.SENIOR),
                (PopulationDimension.SPORT, Sport.ASSOCIATION_FOOTBALL),
                (PopulationDimension.PROFESSIONAL_STATUS, ProfessionalStatus.PROFESSIONAL),
                (PopulationDimension.COMPETITION_TIER, CompetitionTier.TOP_DOMESTIC_DIVISION),
            )
        ),
    )
    return PopulationIdentity(
        sex=Sex.UNKNOWN,
        age_class=AgeClass.SENIOR,
        sport=Sport.ASSOCIATION_FOOTBALL,
        professional_status=ProfessionalStatus.PROFESSIONAL,
        squad_level=SquadLevel.FIRST_TEAM,
        competition_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
        evidence_bindings=bindings,
    )


def source_b_canonical_source() -> CanonicalSource:
    """Build Source B's RES-60 input without upgrading unresolved sex."""

    evidence = RegistryReference(
        identifier=ScientificIdentifier("dynamislm", "evidence", "mendeley-rpl-page", "1.0.0"),
        display_label="Mendeley Source B public metadata",
        reference_ids=(SOURCE_B_LANDING_PAGE,),
    )
    return CanonicalSource(
        source_id=RegistryReference(
            ScientificIdentifier("dynamislm", "dataset", SOURCE_B_ID, "1.0.0"),
            SOURCE_B_SOURCE.title,
        ),
        source_revision=SOURCE_B_VERSION.repository_version,
        population=source_b_population(),
        cohort_scope=CohortScope(
            CohortScopeType.WHOLE_COHORT,
            SubgroupSeparability.EXACT_TARGET_COHORT,
            extraction_evidence=(evidence,),
            provenance_references=(evidence,),
        ),
        data_origin=SourceDataOrigin.ACTUAL_OBSERVED_MEASURED,
        data_granularity=DataGranularity.ATHLETE_LEVEL,
    )


def source_b_quarantine(artifact_sha256: str | None = None) -> QuarantineReceipt:
    """Return the deterministic initial quarantine decision for Source B."""

    decision = qualify_canonical_population(source_b_population())
    if decision.passed:
        raise ValueError("Source B quarantine requires unresolved population evidence")
    source_decision = qualify_canonical_source(source_b_canonical_source())
    reasons = ["UNRESOLVED_SEX_EVIDENCE", "UNRESOLVED_FIRST_TEAM_STATUS"]
    if source_decision.status.value == "UNRESOLVED":
        reasons.append("POPULATION_SCOPE_UNRESOLVED")
    return QuarantineReceipt(
        source_id=SOURCE_B_ID,
        source_version=SOURCE_B_VERSION.repository_version,
        failed_stage="QUALIFY_POPULATION_SOURCE",
        reason_codes=tuple(reasons),
        missing_information=(
            "explicit male-sex evidence for the exact workbook cohort",
            "explicit first-team status for the exact workbook cohort",
        ),
        evidence=(SOURCE_B_LANDING_PAGE,),
        artifact_sha256=artifact_sha256,
        affected_variables=("all athlete-level variables until the cohort sex clause is resolved",),
        requirements_for_requalification=(
            "attach an official source or associated paper passage that explicitly "
            "establishes male participants",
            "rerun the RES-60 canonical population and source decisions",
        ),
    )


def source_b_variable_identities(headers: tuple[str, ...]) -> tuple[SourceVariableIdentity, ...]:
    definitions: dict[str, Mapping[str, object]] = {}
    for header in headers:
        lower = header.lower()
        if "player" in lower or "athlete" in lower or lower.endswith("id"):
            role = SourceVariableRole.CONTEXT.value
        elif any(token in lower for token in ("gps", "distance", "speed", "hsr")):
            role = SourceVariableRole.PROVIDER_DERIVED.value
        elif any(token in lower for token in ("temp", "thermo", "irt")):
            role = SourceVariableRole.DIRECT_REPORTED.value
        else:
            role = SourceVariableRole.UNRESOLVED.value
        definitions[header] = {
            "source_role": role,
            "source_method_family": "Mendeley Source B workbook field",
            "source_definition_reference": SOURCE_B_LANDING_PAGE,
            "resolution_status": (
                VariableResolutionStatus.UNRESOLVED.value
                if role == SourceVariableRole.UNRESOLVED.value
                else VariableResolutionStatus.RESOLVED.value
            ),
        }
    return source_variable_identities(
        headers,
        provider=SOURCE_B_PROVIDER,
        definitions=definitions,
        default_reference=SOURCE_B_LANDING_PAGE,
    )


__all__ = [
    "SOURCE_B_DOI",
    "SOURCE_B_FILE_METADATA_URL",
    "SOURCE_B_FILE_NAME",
    "SOURCE_B_ID",
    "SOURCE_B_LANDING_PAGE",
    "SOURCE_B_LICENSE",
    "SOURCE_B_MAPPING_VERSION",
    "SOURCE_B_PROVIDER",
    "SOURCE_B_SOURCE",
    "SOURCE_B_VERSION",
    "acquire_source_b",
    "fetch_mendeley_file_metadata",
    "inspect_workbook",
    "source_b_canonical_source",
    "source_b_file_metadata",
    "source_b_population",
    "source_b_quarantine",
    "source_b_variable_identities",
    "stable_mendeley_file_metadata",
]
