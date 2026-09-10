"""Deterministic schema and RES-60 qualification helpers for RES-63."""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path

from dynamislm.ingestion.contracts import (
    DatasetLicenseIdentity,
    DatasetQualificationReceipt,
    DatasetQualificationStatus,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    SourceSchema,
    SourceVariableIdentity,
    SourceVariableRole,
    VariableResolutionStatus,
)
from dynamislm.measurement.identity import MetadataEntry, RegistryReference, ScientificIdentifier
from dynamislm.population.models import (
    AgeClass,
    CanonicalSource,
    CohortScope,
    CohortScopeType,
    CompetitionIdentity,
    CompetitionTier,
    DataGranularity,
    EvidenceClass,
    LicenseReuseMetadata,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationEvidenceStatus,
    PopulationIdentity,
    ProfessionalStatus,
    ReuseStatus,
    SeasonIdentity,
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

TabRow = tuple[int, tuple[str, ...]]


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, "1.0.0"),
        display_label=label,
    )


def _structural_type(values: list[str]) -> str:
    present = [value.strip() for value in values if value.strip()]
    if not present:
        return "MISSING_ONLY"
    kinds: set[str] = set()
    for value in present:
        try:
            int(value)
        except ValueError:
            try:
                float(value.replace(",", "."))
            except ValueError:
                lowered = value.lower()
                kinds.add("BOOLEAN" if lowered in {"true", "false", "yes", "no"} else "STRING")
            else:
                kinds.add("FLOAT")
        else:
            kinds.add("INTEGER")
    return next(iter(kinds)) if len(kinds) == 1 else "MIXED"


def iter_tab_rows(path: Path) -> Iterator[TabRow]:
    """Yield one-based source row numbers and exact tab-delimited cell text."""

    try:
        source = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ValueError(f"could not open tabular source: {path}") from exc
    with source:
        reader = csv.reader(source, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("tabular source has no header") from exc
        if not header or any(not column.strip() for column in header):
            raise ValueError("tabular source header must contain non-empty columns")
        expected_width = len(header)
        for row_number, row in enumerate(reader, start=1):
            if len(row) != expected_width:
                raise ValueError(
                    f"source row {row_number} has {len(row)} cells; expected {expected_width}"
                )
            yield row_number, tuple(row)


def tab_header(path: Path) -> tuple[str, ...]:
    """Read and preserve the exact original tabular header spelling."""

    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.reader(source, delimiter="\t")
            header = tuple(next(reader))
    except (OSError, StopIteration) as exc:
        raise ValueError("tabular source must contain a readable header") from exc
    if not header or any(not column.strip() for column in header):
        raise ValueError("tabular source header must contain non-empty columns")
    return header


def inspect_tabular_schema(
    path: Path,
    *,
    source_id: str,
    source_version: str,
    raw_artifact_sha256: str,
    athlete_column: str = "AthleteID",
    game_date_column: str = "Gamedate",
    natural_key_columns: tuple[str, ...] = ("AthleteID", "Gamedate"),
    original_filename: str | None = None,
) -> SourceSchema:
    """Compute schema, missingness, duplicate, and structural type facts."""

    header = tab_header(path)
    positions = {name: index for index, name in enumerate(header)}
    missing = [0 for _ in header]
    values_by_column: list[list[str]] = [[] for _ in header]
    raw_rows: Counter[tuple[str, ...]] = Counter()
    natural_keys: Counter[tuple[str, ...]] = Counter()
    athlete_values: set[str] = set()
    game_dates: set[str] = set()
    row_count = 0
    for row_number, row in iter_tab_rows(path):
        del row_number
        row_count += 1
        raw_rows[row] += 1
        for index, value in enumerate(row):
            values_by_column[index].append(value)
            if not value.strip():
                missing[index] += 1
        if athlete_column in positions:
            value = row[positions[athlete_column]].strip()
            if value:
                athlete_values.add(value)
        if game_date_column in positions:
            value = row[positions[game_date_column]].strip()
            if value:
                game_dates.add(value)
        if all(column in positions for column in natural_key_columns):
            natural_keys[tuple(row[positions[column]] for column in natural_key_columns)] += 1

    duplicate_raw_rows = sum(count - 1 for count in raw_rows.values() if count > 1)
    candidate_natural_key_duplicates = sum(
        count - 1 for count in natural_keys.values() if count > 1
    )
    observed_types = tuple(_structural_type(values) for values in values_by_column)
    schema_payload = {
        "source_id": source_id,
        "source_version": source_version,
        "raw_artifact_sha256": raw_artifact_sha256,
        "original_filename": original_filename or path.name,
        "columns": header,
        "row_count": row_count,
        "column_count": len(header),
        "missing_counts": tuple(missing),
        "duplicate_raw_rows": duplicate_raw_rows,
        "candidate_natural_key_duplicates": candidate_natural_key_duplicates,
        "distinct_athlete_ids": len(athlete_values),
        "distinct_game_dates": len(game_dates),
        "structural_observed_types": observed_types,
    }
    return SourceSchema(
        source_id=source_id,
        source_version=source_version,
        raw_artifact_sha256=raw_artifact_sha256,
        original_filename=original_filename or path.name,
        columns=header,
        row_count=row_count,
        column_count=len(header),
        missing_counts=tuple(
            MetadataEntry(column, count) for column, count in zip(header, missing, strict=True)
        ),
        duplicate_raw_rows=duplicate_raw_rows,
        candidate_natural_key_duplicates=candidate_natural_key_duplicates,
        distinct_athlete_ids=len(athlete_values),
        distinct_game_dates=len(game_dates),
        structural_observed_types=tuple(
            MetadataEntry(column, observed_type)
            for column, observed_type in zip(
                header,
                observed_types,
                strict=True,
            )
        ),
        schema_sha256=canonical_hash(schema_payload),
    )


def source_variable_identities(
    columns: tuple[str, ...],
    *,
    provider: str,
    definitions: Mapping[str, Mapping[str, object]],
    default_reference: str,
) -> tuple[SourceVariableIdentity, ...]:
    """Build one identity per exact source column, preserving unknowns."""

    identities: list[SourceVariableIdentity] = []
    for column in columns:
        definition = definitions.get(column, {})
        role_value = definition.get("source_role", "UNRESOLVED")
        role = role_value if isinstance(role_value, str) else "UNRESOLVED"
        try:
            variable_role = SourceVariableRole(role)
        except ValueError:
            variable_role = SourceVariableRole.UNRESOLVED
        missing_information_value = definition.get("missing_information", ())
        missing_information = (
            tuple(item for item in missing_information_value if isinstance(item, str))
            if isinstance(missing_information_value, tuple | list)
            else ()
        )
        resolution_value = definition.get("resolution_status", "RESOLVED")
        try:
            resolution_status = VariableResolutionStatus(str(resolution_value))
        except ValueError:
            resolution_status = VariableResolutionStatus.UNRESOLVED
        identities.append(
            SourceVariableIdentity(
                original_column_name=column,
                source_label=str(definition.get("source_label", column)),
                source_role=variable_role,
                source_provider=provider,
                source_reported_unit=(
                    str(definition["source_reported_unit"])
                    if definition.get("source_reported_unit") is not None
                    else None
                ),
                source_method_family=(
                    str(definition["source_method_family"])
                    if definition.get("source_method_family") is not None
                    else None
                ),
                source_threshold_or_band=(
                    str(definition["source_threshold_or_band"])
                    if definition.get("source_threshold_or_band") is not None
                    else None
                ),
                source_aggregation_context=(
                    str(definition["source_aggregation_context"])
                    if definition.get("source_aggregation_context") is not None
                    else None
                ),
                source_device_or_sampling_note=(
                    str(definition["source_device_or_sampling_note"])
                    if definition.get("source_device_or_sampling_note") is not None
                    else None
                ),
                source_definition_reference=str(
                    definition.get("source_definition_reference", default_reference)
                ),
                resolution_status=resolution_status,
                missing_information=missing_information,
            )
        )
    return tuple(identities)


def canonical_population_identity(
    evidence_reference: RegistryReference,
    *,
    competition_identity: CompetitionIdentity | None = None,
    season_identity: SeasonIdentity | None = None,
) -> PopulationIdentity:
    """Create the exact V2 target identity with explicit evidence bindings."""

    bindings = tuple(
        PopulationEvidenceBinding(
            dimension=dimension,
            value=value,
            evidence_reference=evidence_reference,
            status=PopulationEvidenceStatus.ESTABLISHED,
        )
        for dimension, value in (
            (PopulationDimension.SEX, Sex.MALE),
            (PopulationDimension.AGE_CLASS, AgeClass.SENIOR),
            (PopulationDimension.SPORT, Sport.ASSOCIATION_FOOTBALL),
            (PopulationDimension.PROFESSIONAL_STATUS, ProfessionalStatus.PROFESSIONAL),
            (PopulationDimension.SQUAD_LEVEL, SquadLevel.FIRST_TEAM),
            (PopulationDimension.COMPETITION_TIER, CompetitionTier.TOP_DOMESTIC_DIVISION),
        )
    )
    return PopulationIdentity(
        sex=Sex.MALE,
        age_class=AgeClass.SENIOR,
        sport=Sport.ASSOCIATION_FOOTBALL,
        professional_status=ProfessionalStatus.PROFESSIONAL,
        squad_level=SquadLevel.FIRST_TEAM,
        competition_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
        competition_identity=competition_identity,
        season=season_identity,
        evidence_bindings=bindings,
    )


def build_canonical_source(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    population: PopulationIdentity,
    *,
    license_identity: DatasetLicenseIdentity,
    evidence_references: tuple[RegistryReference, ...],
    publication_reference: RegistryReference | None = None,
    data_granularity: DataGranularity = DataGranularity.ATHLETE_LEVEL,
) -> CanonicalSource:
    """Compose the existing RES-60 source input without duplicating its gate."""

    reuse_status = (
        ReuseStatus.RESTRICTED
        if license_identity.noncommercial_restriction
        else ReuseStatus.UNRESTRICTED
    )
    license_reference = _reference(
        "license",
        license_identity.spdx_expression.lower(),
        license_identity.spdx_expression,
    )
    return CanonicalSource(
        source_id=_reference("dataset", source.source_id, source.title),
        source_revision=version.repository_version,
        population=population,
        cohort_scope=CohortScope(
            scope_type=CohortScopeType.WHOLE_COHORT,
            separability=SubgroupSeparability.EXACT_TARGET_COHORT,
            extraction_evidence=evidence_references,
            provenance_references=evidence_references,
            description="Exact source cohort described by official provider evidence",
        ),
        data_origin=SourceDataOrigin.ACTUAL_OBSERVED_MEASURED,
        data_granularity=data_granularity,
        publication_reference=publication_reference,
        license_reuse=LicenseReuseMetadata(
            reuse_status=reuse_status,
            license_reference=license_reference,
            conditions=("attribution_required",) if license_identity.attribution_required else (),
        ),
        provenance_references=evidence_references,
    )


def qualify_dataset(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    population: PopulationIdentity,
    canonical_source: CanonicalSource,
    *,
    artifact_sha256: str | None,
    license_captured: bool,
    variable_identities: tuple[SourceVariableIdentity, ...],
    football_mapping_status: VariableResolutionStatus,
    evidence: tuple[str, ...],
) -> DatasetQualificationReceipt:
    """Apply RES-60 and row-boundary gates to one source qualification receipt."""

    population_decision = qualify_canonical_population(population)
    source_decision = qualify_canonical_source(canonical_source)
    statuses = {
        identity.resolution_status
        for identity in variable_identities
        if not (
            identity.source_role is SourceVariableRole.CONTEXT
            and identity.resolution_status is VariableResolutionStatus.QUARANTINED
        )
    }
    variable_status = (
        VariableResolutionStatus.UNRESOLVED
        if not variable_identities
        or SourceVariableRole.UNRESOLVED
        in {identity.source_role for identity in variable_identities}
        or statuses & {VariableResolutionStatus.UNRESOLVED, VariableResolutionStatus.QUARANTINED}
        else VariableResolutionStatus.PARTIAL
        if VariableResolutionStatus.PARTIAL in statuses
        else VariableResolutionStatus.RESOLVED
    )
    reasons: list[str] = []
    if not population_decision.passed:
        reasons.append("POPULATION_GATE_FAILED")
    if not source_decision.passed:
        reasons.append("SOURCE_GATE_FAILED")
    if artifact_sha256 is None:
        reasons.append("RAW_BYTES_UNVERIFIED")
    if not license_captured:
        reasons.append("LICENSE_NOT_CAPTURED")
    if variable_status is VariableResolutionStatus.UNRESOLVED:
        reasons.append("VARIABLE_IDENTITY_UNRESOLVED")
    if football_mapping_status is not VariableResolutionStatus.RESOLVED:
        reasons.append("FOOTBALL_CONTEXT_UNRESOLVED")
    status = (
        DatasetQualificationStatus.QUALIFIED
        if not reasons
        else DatasetQualificationStatus.QUARANTINED
    )
    return DatasetQualificationReceipt(
        source_id=source.source_id,
        source_version=version.repository_version,
        status=status,
        population_decision=population_decision,
        source_decision=source_decision,
        artifact_sha256=artifact_sha256,
        evidence_class=(
            EvidenceClass.CANONICAL_EMPIRICAL_TARGET
            if source_decision.passed
            else EvidenceClass.REJECTED_OR_UNRESOLVED
        ),
        actual_observed_data=True,
        performance_science_relevance=True,
        license_captured=license_captured,
        variable_identity_status=variable_status,
        football_mapping_status=football_mapping_status,
        reason_codes=tuple(reasons),
        missing_information=tuple(reasons),
        evidence=evidence,
    )


__all__ = [
    "TabRow",
    "build_canonical_source",
    "canonical_population_identity",
    "inspect_tabular_schema",
    "iter_tab_rows",
    "qualify_dataset",
    "source_variable_identities",
    "tab_header",
]
