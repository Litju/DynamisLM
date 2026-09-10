"""Source A adapter for the UNIFESP/Domus Dados Serie A ``.tab`` file."""

from __future__ import annotations

import datetime as datetime_module
import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dynamislm.ingestion.acquisition import acquire_url, capture_metadata_snapshot
from dynamislm.ingestion.contracts import (
    CanonicalEmpiricalRecord,
    CanonicalFootballContext,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    FileRepresentation,
    RawRowIdentity,
    RegisteredDatasetFileIdentity,
    SourceMetadataClaim,
    SourceMetadataConflict,
    SourceSchema,
    SourceVariableIdentity,
    SourceVariableRegistry,
    SourceVariableRole,
    VariableResolutionStatus,
)
from dynamislm.ingestion.promotion import build_raw_to_canonical_lineage
from dynamislm.ingestion.qualification import (
    build_canonical_source,
    build_source_variable_registry,
    inspect_tabular_schema,
    iter_tab_rows,
    source_variable_identities,
    tab_header,
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
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    ScientificIdentifier,
)
from dynamislm.population.models import (
    AgeClass,
    CanonicalPopulationDecision,
    CanonicalSourceDecision,
    CompetitionIdentity,
    CompetitionTier,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationIdentity,
    ProfessionalStatus,
    SeasonIdentity,
    Sex,
    Sport,
    SquadLevel,
)
from dynamislm.population.qualification import (
    qualify_canonical_population,
    qualify_canonical_source,
)

SOURCE_A_ID = "unifesp-brazil-serie-a-v1"
SOURCE_A_MAPPING_VERSION = "unifesp-serie-a-mapping@1.1.0"
SOURCE_A_PROVIDER = "UNIFESP Domus Dados / Dataverse"
SOURCE_A_LANDING_PAGE = (
    "https://domusdados.unifesp.br/dataset.xhtml?persistentId=hdl%3A20.500.12682%2Frdp%2FGMXME8"
)
SOURCE_A_METADATA_URL = (
    "https://domusdados.unifesp.br/api/datasets/:persistentId/versions/1.0?"
    "persistentId=hdl%3A20.500.12682%2Frdp%2FGMXME8&excludeFiles=false"
)
SOURCE_A_COLLECTION_DESCRIPTION_URI = "https://domusdados.unifesp.br/dataverse/eappefp"
SOURCE_A_FILE_NAME = (
    "Physical performance data. Data on contextual factors related to physical performance..tab"
)
SOURCE_A_REGISTRY_DOCUMENT = load_dataset_registry(SOURCE_A_ID)
SOURCE_A_REGISTERED_FILE: RegisteredDatasetFileIdentity = registered_dataset_file_identity(
    SOURCE_A_REGISTRY_DOCUMENT,
    representation=FileRepresentation.ARCHIVAL_TAB,
)
SOURCE_A_EXPECTED_SHA256 = SOURCE_A_REGISTERED_FILE.expected_sha256
SOURCE_A_EXPECTED_BYTE_SIZE = SOURCE_A_REGISTERED_FILE.expected_byte_size

SOURCE_A_SOURCE = dataset_source_identity(SOURCE_A_REGISTRY_DOCUMENT)
SOURCE_A_VERSION = dataset_version_identity(SOURCE_A_REGISTRY_DOCUMENT)
SOURCE_A_COMPETITION = CompetitionIdentity(
    identifier=ScientificIdentifier("dynamislm", "competition", "brazil-serie-a", "1.0.0"),
    display_label="Brazilian Serie A",
)
SOURCE_A_LICENSE = dataset_license_identity(SOURCE_A_REGISTRY_DOCUMENT)


def source_a_variable_definitions() -> dict[str, dict[str, object]]:
    """Return source A's explicit column identities from provider metadata."""

    context_columns: dict[str, dict[str, object]] = {
        "AthleteID": {"source_role": SourceVariableRole.CONTEXT.value},
        "Dateofbirth": {
            "source_role": SourceVariableRole.CONTEXT.value,
            "source_reported_unit": "Excel date serial",
            "resolution_status": VariableResolutionStatus.QUARANTINED.value,
            "missing_information": (
                "personal-context field is source-only by RES-63 privacy policy",
            ),
        },
        "Gamedate": {
            "source_role": SourceVariableRole.CONTEXT.value,
            "source_reported_unit": "Excel date serial",
        },
        "Coach": {"source_role": SourceVariableRole.CONTEXT.value},
        "PositionName": {"source_role": SourceVariableRole.CONTEXT.value},
    }
    direct_columns: dict[str, dict[str, object]] = {
        "Weight(kg)": {"source_reported_unit": "kg"},
        "Height(cm)": {"source_reported_unit": "cm"},
        "Age": {"source_reported_unit": "years"},
        "Matchduration(min)": {
            "source_reported_unit": "min",
            "source_aggregation_context": "one source row / athlete / reported match exposure",
        },
    }
    provider_columns: dict[str, dict[str, object]] = {
        "TotalDistance(m)": {"source_reported_unit": "m"},
        "Relativedistance(m/min)": {"source_reported_unit": "m/min"},
        "Distance>20,0km/h(m)": {
            "source_reported_unit": "m",
            "source_threshold_or_band": ">20.0 km/h",
        },
        "Distance>25,0km/h(m)": {
            "source_reported_unit": "m",
            "source_threshold_or_band": ">25.0 km/h",
        },
        "Distance>30,0km/h(m)": {
            "source_reported_unit": "m",
            "source_threshold_or_band": ">30.0 km/h",
        },
        "Explosiveefforts(N)": {
            "source_reported_unit": "N (source label)",
            "source_method_family": "Catapult IMA",
            "source_threshold_or_band": ">3 m/s² explosive action threshold",
        },
        "Maxvelocity(km/h)": {"source_reported_unit": "km/h"},
        "Distance>20W(m)": {
            "source_reported_unit": "m",
            "source_threshold_or_band": ">20 W·kg⁻¹ metabolic-power band",
        },
        "Distance>55W(m)": {
            "source_reported_unit": "m",
            "source_threshold_or_band": ">55 W·kg⁻¹ metabolic-power band",
        },
        "Playerload": {
            "source_method_family": "Catapult PlayerLoad provider output",
            "source_device_or_sampling_note": (
                "VECTOR7 tri-axial accelerometer; proprietary processing parameters not public"
            ),
            "missing_information": ("provider filtering and proprietary algorithm parameters",),
        },
        "Sprints": {
            "source_method_family": "Catapult GPS provider output",
            "source_threshold_or_band": ">25 km/h sprint definition in provider description",
        },
        "Acceleration(N)": {
            "source_reported_unit": "N (source label)",
            "source_method_family": "Catapult IMA provider output",
            "source_threshold_or_band": "acceleration angular band -45° to 0° and 0° to 45°",
        },
        "Deceleration(N)": {
            "source_reported_unit": "N (source label)",
            "source_method_family": "Catapult IMA provider output",
            "source_threshold_or_band": "deceleration angular band 135° to 180° and -180° to -135°",
        },
        "Changeofdirectiontoleft(N)": {
            "source_reported_unit": "N (source label)",
            "source_method_family": "Catapult IMA provider output",
            "source_threshold_or_band": "change-of-direction angular band -135° to -45°",
        },
        "Changeofdirectiontoright(N)": {
            "source_reported_unit": "N (source label)",
            "source_method_family": "Catapult IMA provider output",
            "source_threshold_or_band": "change-of-direction angular band 45° to 135°",
        },
        "Jumps>40cm(IMA)": {
            "source_method_family": "Catapult IMA provider output",
            "source_threshold_or_band": ">40 cm jump definition",
        },
        "RHIEBoutRecoveryMean(s)": {
            "source_reported_unit": "s",
            "source_method_family": "Catapult RHIE provider output",
            "source_threshold_or_band": "three explosive efforts in ≤60 s",
        },
        "RHIETotalBouts(N)": {
            "source_method_family": "Catapult RHIE provider output",
            "source_threshold_or_band": "three explosive efforts in ≤60 s",
        },
        "RHIEEffortsPerBout-Mean": {
            "source_method_family": "Catapult RHIE provider output",
            "source_threshold_or_band": "three explosive efforts in ≤60 s",
        },
    }
    definitions: dict[str, dict[str, object]] = {}
    for column, definition in context_columns.items():
        definitions[column] = {
            **definition,
            "source_label": column,
            "source_definition_reference": SOURCE_A_LANDING_PAGE,
        }
    for column, definition in direct_columns.items():
        definitions[column] = {
            **definition,
            "source_role": SourceVariableRole.DIRECT_REPORTED.value,
            "source_label": column,
            "source_method_family": "source-reported contextual value",
            "source_definition_reference": SOURCE_A_LANDING_PAGE,
        }
    for column, definition in provider_columns.items():
        definitions[column] = {
            **definition,
            "source_role": SourceVariableRole.PROVIDER_DERIVED.value,
            "source_label": column,
            "source_definition_reference": SOURCE_A_LANDING_PAGE,
            "source_device_or_sampling_note": definition.get(
                "source_device_or_sampling_note",
                "Catapult VECTOR7; public table contains derived player-match metrics, not raw "
                "waveforms",
            ),
        }
    return definitions


def source_a_variable_identities(
    columns: tuple[str, ...],
) -> tuple[SourceVariableIdentity, ...]:
    return source_variable_identities(
        columns,
        provider=SOURCE_A_PROVIDER,
        definitions=source_a_variable_definitions(),
        default_reference=SOURCE_A_LANDING_PAGE,
    )


def source_a_variable_registry(
    columns: tuple[str, ...],
) -> SourceVariableRegistry:
    return build_source_variable_registry(
        SOURCE_A_ID,
        SOURCE_A_VERSION.repository_version,
        SOURCE_A_MAPPING_VERSION,
        source_a_variable_identities(columns),
    )


def fetch_source_a_metadata() -> dict[str, Any]:
    """Fetch the official Dataverse metadata for the explicitly pinned version 1.0."""

    request = urllib.request.Request(
        SOURCE_A_METADATA_URL,
        headers={"User-Agent": "DynamisLM-RES63/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Source A Dataverse metadata must be an object")
    return payload


def source_a_file_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract and verify the registered file from Dataverse version 1.0 metadata."""

    data = metadata.get("data")
    if isinstance(data, dict) and isinstance(data.get("datasetVersion"), dict):
        dataset_version = data["datasetVersion"]
    elif isinstance(data, dict) and isinstance(data.get("files"), list):
        dataset_version = data
    else:
        dataset_version = metadata.get("datasetVersion")
    if not isinstance(dataset_version, dict):
        raise ValueError("Source A metadata lacks datasetVersion")
    if dataset_version.get("datasetPersistentId") != SOURCE_A_SOURCE.persistent_identifier:
        raise ValueError("Source A Dataverse metadata identifies the wrong dataset")
    version_number = dataset_version.get("versionNumber")
    version_minor_number = dataset_version.get("versionMinorNumber")
    returned_version = (
        f"{version_number}.{version_minor_number}"
        if version_minor_number is not None
        else str(version_number)
    )
    if returned_version not in {"1", "1.0"}:
        raise ValueError("Source A Dataverse metadata is not version 1.0")
    files = dataset_version.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ValueError("Source A metadata must expose exactly one published file")
    data_file = files[0].get("dataFile")
    if not isinstance(data_file, dict):
        raise ValueError("Source A metadata lacks dataFile identity")
    if data_file.get("id") != SOURCE_A_REGISTERED_FILE.provider_file_id:
        raise ValueError("Source A Dataverse version 1.0 lacks the registered file ID")
    if data_file.get("persistentId") != SOURCE_A_REGISTERED_FILE.file_persistent_identifier:
        raise ValueError("Source A Dataverse version 1.0 lacks the registered file PID")
    if data_file.get("filename") != SOURCE_A_REGISTERED_FILE.filename:
        raise ValueError("Source A Dataverse version 1.0 returned the wrong file")
    return data_file


def acquire_source_a(
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Acquire the published tab file, retaining provider MD5 as supplementary data."""

    metadata_document = metadata if metadata is not None else fetch_source_a_metadata()
    data_file = source_a_file_metadata(metadata_document)
    snapshot_sha256 = capture_metadata_snapshot(
        SOURCE_A_SOURCE,
        SOURCE_A_VERSION,
        metadata_document,
        data_root=data_root,
        repository_root=repository_root,
    )
    file_id = data_file.get("id")
    provider_md5 = data_file.get("md5")
    if isinstance(file_id, bool) or not isinstance(file_id, int):
        raise ValueError("Source A metadata lacks numeric data-file ID")
    if not isinstance(provider_md5, str) or not provider_md5.strip():
        raise ValueError("Source A metadata lacks provider MD5")
    verify_live_provider_file_observation(
        SOURCE_A_REGISTERED_FILE,
        provider_hash=provider_md5,
        provider_hash_algorithm="md5",
        provider_hash_representation=FileRepresentation.SAVED_ORIGINAL,
        provider_file_id=file_id,
    )
    download_url = f"https://domusdados.unifesp.br/api/access/datafile/{file_id}"
    return acquire_url(
        SOURCE_A_SOURCE,
        SOURCE_A_VERSION,
        download_url,
        registered_file_identity=SOURCE_A_REGISTERED_FILE,
        representation=FileRepresentation.ARCHIVAL_TAB,
        provider_file_id=file_id,
        provider_hash=provider_md5,
        provider_hash_algorithm="md5",
        provider_hash_representation=FileRepresentation.SAVED_ORIGINAL,
        metadata_snapshot_sha256=snapshot_sha256,
        original_filename=str(data_file.get("filename", SOURCE_A_FILE_NAME)),
        media_type=str(data_file.get("contentType", "text/tab-separated-values")),
        data_root=data_root,
        repository_root=repository_root,
    )


def source_a_metadata_conflicts(
    *,
    verified_row_count: int,
    verified_distinct_athletes: int,
    verified_distinct_game_dates: int,
    verified_byte_size: int,
    verified_provider_md5: str,
) -> tuple[SourceMetadataConflict, ...]:
    """Retain claim conflicts; representation differences are reported separately."""

    claims = {
        "participant_count": (
            SourceMetadataClaim(
                SOURCE_A_ID,
                "participant_count",
                98,
                SOURCE_A_METADATA_URL,
                "Dataverse version 1.0 description participant count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "participant_count",
                90,
                SOURCE_A_COLLECTION_DESCRIPTION_URI,
                "Domus collection description participant count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "participant_count",
                98,
                "https://doi.org/10.3390/jfmk10040385",
                "paper abstract participant count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "participant_count",
                99,
                "https://doi.org/10.3390/jfmk10040385",
                "paper Methods 2.1 participant count",
            ),
        ),
        "match_count": (
            SourceMetadataClaim(
                SOURCE_A_ID,
                "match_count",
                295,
                SOURCE_A_METADATA_URL,
                "Dataverse version 1.0 description match count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "match_count",
                351,
                SOURCE_A_COLLECTION_DESCRIPTION_URI,
                "Domus collection description official match count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "match_count",
                351,
                "https://doi.org/10.3390/jfmk10040385",
                "paper abstract official match count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "match_count",
                351,
                "https://doi.org/10.3390/jfmk10040385",
                "paper Methods 2.1 official match count",
            ),
        ),
        "case_count": (
            SourceMetadataClaim(
                SOURCE_A_ID,
                "case_count",
                5203,
                SOURCE_A_METADATA_URL,
                "Dataverse version 1.0 description case count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "case_count",
                5203,
                "https://doi.org/10.3390/jfmk10040385",
                "paper abstract and Methods case count",
            ),
            SourceMetadataClaim(
                SOURCE_A_ID,
                "case_count",
                verified_row_count,
                SOURCE_A_METADATA_URL,
                "verified table rows",
            ),
        ),
    }
    verified_facts: dict[str, str | int | None] = {
        "participant_count": verified_distinct_athletes,
        "match_count": None,
        "case_count": verified_row_count,
    }
    return tuple(
        SourceMetadataConflict(
            source_id=SOURCE_A_ID,
            source_version=SOURCE_A_VERSION.repository_version,
            field=field,
            claims=field_claims,
            verified_file_fact=verified_facts[field],
        )
        for field, field_claims in claims.items()
        if len({repr(claim.value) for claim in field_claims}) > 1
    )


def source_a_representation_audit(
    *,
    verified_archival_sha256: str,
    verified_archival_byte_size: int,
    verified_saved_original_md5: str,
    verified_saved_original_byte_size: int,
) -> dict[str, object]:
    """Record Dataverse archival-vs-original provenance without conflating bytes."""

    return {
        "classification": "FILE_REPRESENTATION_DIFFERENCE",
        "selected_ingestion_representation": FileRepresentation.ARCHIVAL_TAB.value,
        "provider_hash": SOURCE_A_REGISTERED_FILE.provider_hash,
        "provider_hash_role": FileRepresentation.SAVED_ORIGINAL.value,
        "provider_hash_verified": (
            verified_saved_original_md5.lower()
            == (SOURCE_A_REGISTERED_FILE.provider_hash or "").lower()
        ),
        "provider_declared_byte_size": SOURCE_A_REGISTERED_FILE.provider_declared_byte_size,
        "archival_tab": {
            "sha256": verified_archival_sha256,
            "byte_size": verified_archival_byte_size,
        },
        "saved_original": {
            "filename": "Raw data.xlsx",
            "md5": verified_saved_original_md5,
            "byte_size": verified_saved_original_byte_size,
            "stored": False,
            "canonical": False,
        },
    }


def source_a_population_identity() -> PopulationIdentity:
    """Build Source A population identity from dimension-specific official evidence."""

    paper_uri = "https://doi.org/10.3390/jfmk10040385"

    def evidence(key: str, label: str, uri: str, location: str) -> RegistryReference:
        return RegistryReference(
            identifier=ScientificIdentifier("dynamislm", "evidence", key, "1.1.0"),
            display_label=label,
            reference_ids=(uri,),
        )

    bindings = (
        PopulationEvidenceBinding(
            PopulationDimension.SEX,
            Sex.MALE,
            evidence(
                "source-a-paper-methods-sex",
                "Source A paper Methods 2.1: 99 male professional football players",
                paper_uri,
                "Methods 2.1 Subjects",
            ),
            source_note="Methods 2.1 explicitly states male participants.",
        ),
        PopulationEvidenceBinding(
            PopulationDimension.AGE_CLASS,
            AgeClass.SENIOR,
            evidence(
                "source-a-paper-methods-age",
                "Source A paper Methods 2.1: age 18 to 40 years",
                paper_uri,
                "Methods 2.1 Subjects",
            ),
            source_note="The reported cohort range is adult/senior, not U23 or youth.",
        ),
        PopulationEvidenceBinding(
            PopulationDimension.SPORT,
            Sport.ASSOCIATION_FOOTBALL,
            evidence(
                "source-a-paper-methods-sport",
                "Source A paper Methods 2.1: Brazilian First Division football",
                paper_uri,
                "Methods 2.1 Subjects",
            ),
            source_note="The paper identifies football match performance.",
        ),
        PopulationEvidenceBinding(
            PopulationDimension.PROFESSIONAL_STATUS,
            ProfessionalStatus.PROFESSIONAL,
            evidence(
                "source-a-paper-methods-professional",
                "Source A paper Methods 2.1: professional football players",
                paper_uri,
                "Methods 2.1 Subjects",
            ),
            source_note="The paper uses the exact professional-player wording.",
        ),
        PopulationEvidenceBinding(
            PopulationDimension.SQUAD_LEVEL,
            SquadLevel.FIRST_TEAM,
            evidence(
                "source-a-paper-main-team",
                "Source A paper Section 5: main team (professional adult)",
                paper_uri,
                "Section 5 Conclusions",
            ),
            source_note="Exact main-team/professional-adult wording supports first-team status.",
        ),
        PopulationEvidenceBinding(
            PopulationDimension.COMPETITION_TIER,
            CompetitionTier.TOP_DOMESTIC_DIVISION,
            evidence(
                "source-a-paper-first-division",
                "Source A paper Methods 2.1: Brazilian First Division",
                paper_uri,
                "Methods 2.1 Subjects",
            ),
            source_note="Brazilian First Division is the source-supported top domestic tier.",
        ),
    )
    return PopulationIdentity(
        sex=Sex.MALE,
        age_class=AgeClass.SENIOR,
        sport=Sport.ASSOCIATION_FOOTBALL,
        professional_status=ProfessionalStatus.PROFESSIONAL,
        squad_level=SquadLevel.FIRST_TEAM,
        competition_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
        competition_identity=SOURCE_A_COMPETITION,
        evidence_bindings=bindings,
    )


def source_a_population_and_source_decisions() -> tuple[
    CanonicalPopulationDecision, CanonicalSourceDecision
]:
    """Build Source A's exact target decisions through the existing RES-60 authority."""

    population = source_a_population_identity()
    evidence_references = tuple(
        binding.evidence_reference
        for binding in population.evidence_bindings
        if binding.evidence_reference is not None
    )
    assert all(reference is not None for reference in evidence_references)
    source = build_canonical_source(
        SOURCE_A_SOURCE,
        SOURCE_A_VERSION,
        population,
        license_identity=SOURCE_A_LICENSE,
        evidence_references=evidence_references,
        publication_reference=RegistryReference(
            ScientificIdentifier("dynamislm", "publication", "source-a-paper", "1.0.0"),
            "The Aging Curve: How Age Affects Physical Performance in Elite Football",
            reference_ids=("https://doi.org/10.3390/jfmk10040385",),
        ),
    )
    return qualify_canonical_population(population), qualify_canonical_source(source)


def _parse_excel_serial_date(value: str) -> datetime_module.date:
    text = value.strip()
    if not text:
        raise ValueError("Source A row has no Gamedate")
    for format_string in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime_module.datetime.strptime(text, format_string).date()
        except ValueError:
            pass
    try:
        serial = float(text.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"unsupported Source A Gamedate value: {value!r}") from exc
    return datetime_module.date(1899, 12, 30) + datetime_module.timedelta(days=int(serial))


def _source_value(value: str) -> str | int | float | None:
    text = value.strip()
    if not text:
        return None
    try:
        integer = int(text)
    except ValueError:
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return text
    return integer


def source_a_season_identity(observed_date: datetime_module.date) -> SeasonIdentity:
    """Map only the registered 2020-2024 Brazilian Serie A seasons."""

    if observed_date.year not in {2020, 2021, 2022, 2023, 2024}:
        raise ValueError(
            f"Source A date {observed_date.isoformat()} is outside the registered 2020-2024 seasons"
        )
    return SeasonIdentity(
        identifier=ScientificIdentifier(
            "dynamislm",
            "season",
            f"brazil-serie-a-{observed_date.year}",
            "1.0.0",
        ),
        display_label=f"Brazilian Serie A {observed_date.year}",
    )


def map_source_a_records(
    path: Path,
    *,
    raw_artifact_sha256: str,
    schema_sha256: str,
    acquisition_receipt_id: str,
    population_decision: CanonicalPopulationDecision,
    source_decision: CanonicalSourceDecision,
    source: DatasetSourceIdentity = SOURCE_A_SOURCE,
    version: DatasetVersionIdentity = SOURCE_A_VERSION,
    competition_identity: CompetitionIdentity = SOURCE_A_COMPETITION,
    include_source_only_context: bool = False,
) -> Iterator[CanonicalEmpiricalRecord]:
    """Map verified Source A rows without deriving any external-load metric."""

    if not population_decision.passed or not source_decision.passed:
        raise ValueError("Source A canonical mapping requires passing RES-60 decisions")
    actual_digest, _ = file_digest_and_size(path)
    if actual_digest != raw_artifact_sha256:
        raise ValueError("Source A adapter received bytes with the wrong SHA-256 digest")
    actual_schema = inspect_source_a(path, raw_artifact_sha256)
    if actual_schema.schema_sha256 != schema_sha256:
        raise ValueError("Source A adapter received the wrong schema identity")
    if acquisition_receipt_id != f"acquisition:{raw_artifact_sha256}":
        raise ValueError("Source A adapter received the wrong acquisition receipt identity")
    columns = tab_header(path)
    identities = {item.original_column_name: item for item in source_a_variable_identities(columns)}
    for row_number, row in iter_tab_rows(path):
        values = dict(zip(columns, row, strict=True))
        athlete_value = values.get("AthleteID", "").strip()
        if not athlete_value:
            raise ValueError(f"Source A row {row_number} has no AthleteID")
        observed_date = _parse_excel_serial_date(values.get("Gamedate", ""))
        athlete_id = InstanceIdentifier("athlete", athlete_value)
        session_id = InstanceIdentifier(
            "session", f"{source.source_id}:official-match-date:{observed_date.isoformat()}"
        )
        position = values.get("PositionName", "").strip() or None
        football_context = CanonicalFootballContext(
            athlete_id=athlete_id,
            session_id=session_id,
            observed_date=observed_date,
            competition_identity=competition_identity,
            season_identity=source_a_season_identity(observed_date),
            position=position,
        )
        natural_key = "|".join(values.get(column, "") for column in ("AthleteID", "Gamedate"))
        row_identity = RawRowIdentity(
            source_id=source.source_id,
            source_version=version.repository_version,
            raw_artifact_sha256=raw_artifact_sha256,
            source_row_number=row_number,
            natural_source_key=natural_key or None,
            source_athlete_id=athlete_value,
        )
        for column in columns:
            if column == "Dateofbirth" and not include_source_only_context:
                continue
            variable_identity = identities[column]
            if variable_identity.resolution_status is VariableResolutionStatus.QUARANTINED:
                continue
            canonical_key = f"{source.source_id}:{version.repository_version}:{row_number}:{column}"
            lineage = build_raw_to_canonical_lineage(
                source_id=source.source_id,
                source_version=version.repository_version,
                raw_artifact_sha256=raw_artifact_sha256,
                acquisition_receipt_id=acquisition_receipt_id,
                schema_sha256=schema_sha256,
                source_row_number=row_number,
                mapping_version=SOURCE_A_MAPPING_VERSION,
                canonical_record_id=canonical_key,
            )
            yield CanonicalEmpiricalRecord(
                source_identity=source,
                version_identity=version,
                raw_row_identity=row_identity,
                football_context=football_context,
                variable_identity=variable_identity,
                source_reported_value=_source_value(values[column]),
                population_decision=population_decision,
                source_decision=source_decision,
                mapping_version=SOURCE_A_MAPPING_VERSION,
                lineage=lineage,
            )


def inspect_source_a(path: Path, raw_artifact_sha256: str) -> SourceSchema:
    """Inspect Source A's exact tabular structure."""

    return inspect_tabular_schema(
        path,
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_artifact_sha256=raw_artifact_sha256,
        original_filename=SOURCE_A_FILE_NAME,
    )


__all__ = [
    "SOURCE_A_COLLECTION_DESCRIPTION_URI",
    "SOURCE_A_COMPETITION",
    "SOURCE_A_EXPECTED_BYTE_SIZE",
    "SOURCE_A_EXPECTED_SHA256",
    "SOURCE_A_FILE_NAME",
    "SOURCE_A_ID",
    "SOURCE_A_LANDING_PAGE",
    "SOURCE_A_LICENSE",
    "SOURCE_A_MAPPING_VERSION",
    "SOURCE_A_METADATA_URL",
    "SOURCE_A_PROVIDER",
    "SOURCE_A_REGISTERED_FILE",
    "SOURCE_A_SOURCE",
    "SOURCE_A_VERSION",
    "acquire_source_a",
    "fetch_source_a_metadata",
    "inspect_source_a",
    "map_source_a_records",
    "source_a_file_metadata",
    "source_a_metadata_conflicts",
    "source_a_population_and_source_decisions",
    "source_a_population_identity",
    "source_a_representation_audit",
    "source_a_season_identity",
    "source_a_variable_definitions",
    "source_a_variable_identities",
    "source_a_variable_registry",
]
