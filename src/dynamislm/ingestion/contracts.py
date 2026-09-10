"""Immutable contracts for the RES-63 dataset-ingestion boundary.

These objects describe source identity, byte integrity, qualification, mapping,
and the narrow empirical intermediate used before any RES-64 computation.  A
source-reported value remains an external observation; it is not a
DynamisLM-derived measurement result.
"""

from __future__ import annotations

import datetime as datetime_module
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ScientificIdentifier,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
)
from dynamislm.population.models import (
    CanonicalPopulationDecision,
    CanonicalSourceDecision,
    CompetitionIdentity,
    EvidenceClass,
    SeasonIdentity,
)
from dynamislm.serialization import register_serializable_type

type JSONScalar = str | int | float | bool | None

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RELATIVE_PATH_PREFIXES = ("objects/", "metadata/", "receipts/", "canonical/", "quarantine/")


def _digest(value: object, field_name: str) -> str:
    _require_text(value, field_name)
    assert isinstance(value, str)
    digest = value.removeprefix("sha256:")
    if _SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return f"sha256:{digest.lower()}"


def _optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field_name)


def _nonnegative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _json_scalar(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, str | int | float | bool):
        raise ValueError(f"{field_name} must be a JSON scalar or None")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field_name} must not be NaN or Infinity")


def _text_tuple(value: object, field_name: str) -> None:
    _require_tuple_items(value, str, field_name)
    assert isinstance(value, tuple)
    if any(not item.strip() for item in value):
        raise ValueError(f"{field_name} must not contain empty strings")


def _relative_path(value: object, field_name: str) -> None:
    _require_text(value, field_name)
    assert isinstance(value, str)
    if value.startswith("/") or ":\\" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a repository-external relative path")
    if not value.startswith(_RELATIVE_PATH_PREFIXES):
        raise ValueError(f"{field_name} must be relative to DYNAMISLM_DATA_ROOT")


class SourceVariableRole(StrEnum):
    CONTEXT = "CONTEXT"
    DIRECT_REPORTED = "DIRECT_REPORTED"
    PROVIDER_DERIVED = "PROVIDER_DERIVED"
    UNRESOLVED = "UNRESOLVED"


class VariableResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    QUARANTINED = "QUARANTINED"


class DatasetQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class PromotionStatus(StrEnum):
    PROMOTED = "PROMOTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DatasetSourceIdentity:
    """Repository/provider identity independent of any one file revision."""

    source_id: str
    provider: str
    title: str
    landing_page_uri: str
    persistent_identifier: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("provider", self.provider),
            ("title", self.title),
            ("landing_page_uri", self.landing_page_uri),
            ("persistent_identifier", self.persistent_identifier),
        ):
            _require_text(value, field_name)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DatasetVersionIdentity:
    """Version identity; equal labels do not establish equal source bytes."""

    repository_version: str
    version_specific_persistent_identifier: str | None = None
    published_at: datetime_module.datetime | datetime_module.date | None = None

    def __post_init__(self) -> None:
        _require_text(self.repository_version, "repository_version")
        if self.version_specific_persistent_identifier is not None:
            _require_text(
                self.version_specific_persistent_identifier,
                "version_specific_persistent_identifier",
            )
        if self.published_at is not None and not isinstance(
            self.published_at,
            datetime_module.date,
        ):
            raise ValueError("published_at must be a date or datetime when present")
        if isinstance(self.published_at, datetime_module.datetime):
            if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
                raise ValueError("published_at datetime must include an explicit timezone")

    @property
    def version(self) -> str:
        return self.repository_version


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DatasetLicenseIdentity:
    """Small machine-readable license contract for currently supported licenses."""

    spdx_expression: str
    canonical_uri: str
    assertion_source_uri: str
    attribution_required: bool
    noncommercial_restriction: bool
    notes: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.spdx_expression, "spdx_expression")
        if self.spdx_expression not in {"CC-BY-4.0", "CC-BY-NC-4.0"}:
            raise ValueError("unsupported license SPDX expression")
        _require_text(self.canonical_uri, "canonical_uri")
        _require_text(self.assertion_source_uri, "assertion_source_uri")
        if not isinstance(self.attribution_required, bool):
            raise ValueError("attribution_required must be a boolean")
        if not isinstance(self.noncommercial_restriction, bool):
            raise ValueError("noncommercial_restriction must be a boolean")
        expected_noncommercial = self.spdx_expression == "CC-BY-NC-4.0"
        if self.noncommercial_restriction is not expected_noncommercial:
            raise ValueError("license restriction flags do not match SPDX expression")
        if self.notes is not None:
            _require_text(self.notes, "notes")

    @property
    def license_spdx_expression(self) -> str:
        return self.spdx_expression

    @property
    def license_canonical_uri(self) -> str:
        return self.canonical_uri

    @property
    def license_assertion_source(self) -> str:
        return self.assertion_source_uri


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ArtifactAcquisitionReceipt:
    """Receipt for one streamed exact-byte acquisition."""

    source_id: str
    source_version: str
    requested_url: str
    resolved_url: str
    original_filename: str
    media_type: str
    byte_size: int
    sha256: str
    retrieved_at: datetime_module.datetime
    provider_hash: str | None = None
    provider_hash_algorithm: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    metadata_snapshot_sha256: str | None = None
    storage_relative_path: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("requested_url", self.requested_url),
            ("resolved_url", self.resolved_url),
            ("original_filename", self.original_filename),
            ("media_type", self.media_type),
        ):
            _require_text(value, field_name)
        _nonnegative_int(self.byte_size, "byte_size")
        object.__setattr__(self, "sha256", _digest(self.sha256, "sha256"))
        if not isinstance(self.retrieved_at, datetime_module.datetime):
            raise ValueError("retrieved_at must be a datetime")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include an explicit timezone")
        if self.provider_hash is not None:
            _require_text(self.provider_hash, "provider_hash")
        if self.provider_hash_algorithm is not None:
            _require_text(self.provider_hash_algorithm, "provider_hash_algorithm")
        if self.etag is not None:
            _require_text(self.etag, "etag")
        if self.last_modified is not None:
            _require_text(self.last_modified, "last_modified")
        object.__setattr__(
            self,
            "metadata_snapshot_sha256",
            _optional_digest(self.metadata_snapshot_sha256, "metadata_snapshot_sha256"),
        )
        if self.storage_relative_path:
            _relative_path(self.storage_relative_path, "storage_relative_path")

    @property
    def final_url(self) -> str:
        return self.resolved_url


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VerifiedRawArtifact:
    """A verified content-addressed source artifact, named by its digest."""

    artifact_id: InstanceIdentifier
    sha256: str
    byte_size: int
    media_type: str
    relative_path: str
    acquisition_receipt: ArtifactAcquisitionReceipt

    def __post_init__(self) -> None:
        _require_instance(self.artifact_id, InstanceIdentifier, "artifact_id")
        if self.artifact_id.instance_type != "artifact":
            raise ValueError("artifact_id must identify an artifact")
        object.__setattr__(self, "sha256", _digest(self.sha256, "sha256"))
        _nonnegative_int(self.byte_size, "byte_size")
        _require_text(self.media_type, "media_type")
        _relative_path(self.relative_path, "relative_path")
        _require_instance(
            self.acquisition_receipt,
            ArtifactAcquisitionReceipt,
            "acquisition_receipt",
        )
        if self.acquisition_receipt.sha256 != self.sha256:
            raise ValueError("artifact digest must match acquisition receipt")
        if self.acquisition_receipt.byte_size != self.byte_size:
            raise ValueError("artifact byte size must match acquisition receipt")
        if (
            self.acquisition_receipt.storage_relative_path
            and self.acquisition_receipt.storage_relative_path != self.relative_path
        ):
            raise ValueError("artifact path must match acquisition receipt storage path")

    @property
    def raw_artifact_sha256(self) -> str:
        return self.sha256


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceMetadataClaim:
    """One provider/official metadata assertion, retained without adjudication."""

    source_id: str
    field: str
    value: JSONScalar
    assertion_source_uri: str
    claim_label: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.field, "field")
        _json_scalar(self.value, "value")
        _require_text(self.assertion_source_uri, "assertion_source_uri")
        if self.claim_label is not None:
            _require_text(self.claim_label, "claim_label")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceMetadataConflict:
    """Explicit conflict between official/provider claims for one field."""

    source_id: str
    source_version: str
    field: str
    claims: tuple[SourceMetadataClaim, ...]
    verified_file_fact: JSONScalar | None = None
    resolution: str = "UNRESOLVED_PROVIDER_CLAIMS"

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_text(self.field, "field")
        _require_tuple_items(self.claims, SourceMetadataClaim, "claims")
        if len(self.claims) < 2:
            raise ValueError("a metadata conflict requires at least two claims")
        if any(
            claim.source_id != self.source_id or claim.field != self.field for claim in self.claims
        ):
            raise ValueError("metadata conflict claims must identify the same source field")
        if len({(type(claim.value), claim.value) for claim in self.claims}) < 2:
            raise ValueError("metadata conflict claims must disagree")
        _json_scalar(self.verified_file_fact, "verified_file_fact")
        _require_text(self.resolution, "resolution")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceSchema:
    """Deterministic structural facts computed from verified source bytes."""

    source_id: str
    source_version: str
    raw_artifact_sha256: str
    original_filename: str
    columns: tuple[str, ...]
    row_count: int
    column_count: int
    missing_counts: tuple[MetadataEntry, ...]
    duplicate_raw_rows: int
    candidate_natural_key_duplicates: int
    distinct_athlete_ids: int
    distinct_game_dates: int
    structural_observed_types: tuple[MetadataEntry, ...]
    schema_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        object.__setattr__(
            self, "raw_artifact_sha256", _digest(self.raw_artifact_sha256, "raw_artifact_sha256")
        )
        _require_text(self.original_filename, "original_filename")
        _require_tuple_items(self.columns, str, "columns")
        if not self.columns or any(not column.strip() for column in self.columns):
            raise ValueError("columns must be non-empty and contain no blank headers")
        _nonnegative_int(self.row_count, "row_count")
        _nonnegative_int(self.column_count, "column_count")
        if self.column_count != len(self.columns):
            raise ValueError("column_count must equal the number of columns")
        _require_tuple_items(self.missing_counts, MetadataEntry, "missing_counts")
        _nonnegative_int(self.duplicate_raw_rows, "duplicate_raw_rows")
        _nonnegative_int(
            self.candidate_natural_key_duplicates,
            "candidate_natural_key_duplicates",
        )
        _nonnegative_int(self.distinct_athlete_ids, "distinct_athlete_ids")
        _nonnegative_int(self.distinct_game_dates, "distinct_game_dates")
        _require_tuple_items(
            self.structural_observed_types,
            MetadataEntry,
            "structural_observed_types",
        )
        object.__setattr__(self, "schema_sha256", _digest(self.schema_sha256, "schema_sha256"))

    @property
    def header(self) -> tuple[str, ...]:
        return self.columns


@register_serializable_type
@dataclass(frozen=True, slots=True)
class WorkbookSheetSchema:
    """Structural facts for one worksheet inspected without imputation."""

    sheet_name: str
    headers: tuple[str, ...]
    used_range: str
    row_count: int
    column_count: int
    missing_counts: tuple[MetadataEntry, ...]
    structural_observed_types: tuple[MetadataEntry, ...]
    distinct_athlete_ids: int
    distinct_match_or_date_ids: int
    identified_field_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.sheet_name, "sheet_name")
        _require_tuple_items(self.headers, str, "headers")
        if not self.headers or any(not header.strip() for header in self.headers):
            raise ValueError("headers must be non-empty and contain no blank values")
        _require_text(self.used_range, "used_range")
        _nonnegative_int(self.row_count, "row_count")
        _nonnegative_int(self.column_count, "column_count")
        if self.column_count != len(self.headers):
            raise ValueError("column_count must equal the number of headers")
        _require_tuple_items(self.missing_counts, MetadataEntry, "missing_counts")
        _require_tuple_items(
            self.structural_observed_types,
            MetadataEntry,
            "structural_observed_types",
        )
        _nonnegative_int(self.distinct_athlete_ids, "distinct_athlete_ids")
        _nonnegative_int(self.distinct_match_or_date_ids, "distinct_match_or_date_ids")
        _text_tuple(self.identified_field_groups, "identified_field_groups")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class WorkbookSchema:
    """Deterministic workbook-level source schema identity."""

    source_id: str
    source_version: str
    raw_artifact_sha256: str
    sheets: tuple[WorkbookSheetSchema, ...]
    schema_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        object.__setattr__(
            self, "raw_artifact_sha256", _digest(self.raw_artifact_sha256, "raw_artifact_sha256")
        )
        _require_tuple_items(self.sheets, WorkbookSheetSchema, "sheets")
        if not self.sheets:
            raise ValueError("workbook schema must contain at least one worksheet")
        object.__setattr__(self, "schema_sha256", _digest(self.schema_sha256, "schema_sha256"))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceVariableIdentity:
    """Identity of one provider column before any RES-64 computation."""

    original_column_name: str
    source_label: str
    source_role: SourceVariableRole
    source_provider: str
    source_reported_unit: str | None = None
    source_method_family: str | None = None
    source_threshold_or_band: str | None = None
    source_aggregation_context: str | None = None
    source_device_or_sampling_note: str | None = None
    source_definition_reference: str | None = None
    resolution_status: VariableResolutionStatus = VariableResolutionStatus.RESOLVED
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("original_column_name", self.original_column_name),
            ("source_label", self.source_label),
            ("source_provider", self.source_provider),
        ):
            _require_text(value, field_name)
        _require_enum(self.source_role, SourceVariableRole, "source_role")
        for field_name, text_value in (
            ("source_reported_unit", self.source_reported_unit),
            ("source_method_family", self.source_method_family),
            ("source_threshold_or_band", self.source_threshold_or_band),
            ("source_aggregation_context", self.source_aggregation_context),
            ("source_device_or_sampling_note", self.source_device_or_sampling_note),
            ("source_definition_reference", self.source_definition_reference),
        ):
            if text_value is not None:
                _require_text(text_value, field_name)
        _require_enum(self.resolution_status, VariableResolutionStatus, "resolution_status")
        _text_tuple(self.missing_information, "missing_information")
        if self.source_role is SourceVariableRole.UNRESOLVED and (
            self.resolution_status is VariableResolutionStatus.RESOLVED
        ):
            raise ValueError("an unresolved source variable cannot have RESOLVED status")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalFootballContext:
    """Source-supported athlete/session placement for the ingestion intermediate.

    This deliberately does not pretend that a source-date key is a complete
    RES-61 MatchSession.  Unsupported opponent, fixture, venue, and
    match-day-relative fields remain absent rather than being synthesized.
    """

    athlete_id: InstanceIdentifier
    session_id: InstanceIdentifier
    observed_date: datetime_module.date
    competition_identity: CompetitionIdentity | None = None
    season_identity: SeasonIdentity | None = None
    position: str | None = None
    session_kind: str = "OFFICIAL_MATCH"

    def __post_init__(self) -> None:
        _require_instance(self.athlete_id, InstanceIdentifier, "athlete_id")
        if self.athlete_id.instance_type != "athlete":
            raise ValueError("athlete_id must identify an athlete")
        _require_instance(self.session_id, InstanceIdentifier, "session_id")
        if self.session_id.instance_type != "session":
            raise ValueError("session_id must identify a session")
        if isinstance(self.observed_date, datetime_module.datetime) or not isinstance(
            self.observed_date,
            datetime_module.date,
        ):
            raise ValueError("observed_date must be a calendar date")
        _require_optional_instance(
            self.competition_identity,
            CompetitionIdentity,
            "competition_identity",
        )
        _require_optional_instance(self.season_identity, SeasonIdentity, "season_identity")
        if self.position is not None:
            _require_text(self.position, "position")
        _require_text(self.session_kind, "session_kind")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RawRowIdentity:
    """Stable row identity that never assumes AthleteID + date is unique."""

    source_id: str
    source_version: str
    raw_artifact_sha256: str
    source_row_number: int
    natural_source_key: str | None = None
    source_athlete_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        object.__setattr__(
            self, "raw_artifact_sha256", _digest(self.raw_artifact_sha256, "raw_artifact_sha256")
        )
        if isinstance(self.source_row_number, bool) or not isinstance(self.source_row_number, int):
            raise ValueError("source_row_number must be an integer")
        if self.source_row_number < 1:
            raise ValueError("source_row_number must be one-based")
        if self.natural_source_key is not None:
            _require_text(self.natural_source_key, "natural_source_key")
        if self.source_athlete_id is not None:
            _require_text(self.source_athlete_id, "source_athlete_id")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DatasetQualificationReceipt:
    """Source/population qualification plus independent ingestion gates."""

    source_id: str
    source_version: str
    status: DatasetQualificationStatus
    population_decision: CanonicalPopulationDecision | None = None
    source_decision: CanonicalSourceDecision | None = None
    artifact_sha256: str | None = None
    evidence_class: EvidenceClass | None = None
    actual_observed_data: bool = False
    performance_science_relevance: bool = False
    license_captured: bool = False
    variable_identity_status: VariableResolutionStatus = VariableResolutionStatus.UNRESOLVED
    football_mapping_status: VariableResolutionStatus = VariableResolutionStatus.UNRESOLVED
    reason_codes: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_enum(self.status, DatasetQualificationStatus, "status")
        _require_optional_instance(
            self.population_decision,
            CanonicalPopulationDecision,
            "population_decision",
        )
        _require_optional_instance(self.source_decision, CanonicalSourceDecision, "source_decision")
        object.__setattr__(
            self, "artifact_sha256", _optional_digest(self.artifact_sha256, "artifact_sha256")
        )
        if self.evidence_class is not None:
            _require_enum(self.evidence_class, EvidenceClass, "evidence_class")
        if not isinstance(self.actual_observed_data, bool):
            raise ValueError("actual_observed_data must be a boolean")
        if not isinstance(self.performance_science_relevance, bool):
            raise ValueError("performance_science_relevance must be a boolean")
        if not isinstance(self.license_captured, bool):
            raise ValueError("license_captured must be a boolean")
        _require_enum(
            self.variable_identity_status,
            VariableResolutionStatus,
            "variable_identity_status",
        )
        _require_enum(
            self.football_mapping_status,
            VariableResolutionStatus,
            "football_mapping_status",
        )
        _text_tuple(self.reason_codes, "reason_codes")
        _text_tuple(self.missing_information, "missing_information")
        _text_tuple(self.evidence, "evidence")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QuarantineReceipt:
    """First-class fail-closed explanation for a source, row, or variable."""

    source_id: str
    source_version: str
    failed_stage: str
    reason_codes: tuple[str, ...]
    missing_information: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    artifact_sha256: str | None = None
    affected_rows: tuple[int, ...] = ()
    affected_variables: tuple[str, ...] = ()
    requirements_for_requalification: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_text(self.failed_stage, "failed_stage")
        _text_tuple(self.reason_codes, "reason_codes")
        _text_tuple(self.missing_information, "missing_information")
        _text_tuple(self.evidence, "evidence")
        object.__setattr__(
            self, "artifact_sha256", _optional_digest(self.artifact_sha256, "artifact_sha256")
        )
        if not isinstance(self.affected_rows, tuple):
            raise ValueError("affected_rows must be an immutable tuple")
        for row in self.affected_rows:
            if isinstance(row, bool) or not isinstance(row, int) or row < 1:
                raise ValueError("affected_rows must contain positive integers")
        _text_tuple(self.affected_variables, "affected_variables")
        _text_tuple(
            self.requirements_for_requalification,
            "requirements_for_requalification",
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalEmpiricalRecord:
    """One source-row/variable empirical observation before RES-64 science."""

    source_identity: DatasetSourceIdentity
    version_identity: DatasetVersionIdentity
    raw_row_identity: RawRowIdentity
    football_context: CanonicalFootballContext
    variable_identity: SourceVariableIdentity
    source_reported_value: JSONScalar
    population_decision: CanonicalPopulationDecision
    source_decision: CanonicalSourceDecision
    mapping_version: str
    lineage: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_instance(self.source_identity, DatasetSourceIdentity, "source_identity")
        _require_instance(self.version_identity, DatasetVersionIdentity, "version_identity")
        _require_instance(self.raw_row_identity, RawRowIdentity, "raw_row_identity")
        _require_instance(self.football_context, CanonicalFootballContext, "football_context")
        _require_instance(self.variable_identity, SourceVariableIdentity, "variable_identity")
        _json_scalar(self.source_reported_value, "source_reported_value")
        _require_instance(
            self.population_decision,
            CanonicalPopulationDecision,
            "population_decision",
        )
        _require_instance(self.source_decision, CanonicalSourceDecision, "source_decision")
        _require_text(self.mapping_version, "mapping_version")
        _text_tuple(self.lineage, "lineage")
        if self.source_identity.source_id != self.raw_row_identity.source_id:
            raise ValueError("source identity and raw row source IDs must match")
        if self.version_identity.repository_version != self.raw_row_identity.source_version:
            raise ValueError("source version and raw row versions must match")
        if self.source_decision.source.source_id.identifier.key != self.source_identity.source_id:
            raise ValueError("source decision and source identity IDs must match")
        if self.source_decision.population_decision != self.population_decision:
            raise ValueError("source and population decisions must refer to the same qualification")
        if (
            self.raw_row_identity.source_athlete_id is not None
            and self.raw_row_identity.source_athlete_id != self.football_context.athlete_id.value
        ):
            raise ValueError("raw row athlete and football context athlete IDs must match")
        expected_canonical_id = (
            f"{self.source_identity.source_id}:{self.version_identity.repository_version}:"
            f"{self.raw_row_identity.source_row_number}:"
            f"{self.variable_identity.original_column_name}"
        )
        expected_lineage = (
            f"dataset-source:{self.source_identity.source_id}",
            f"dataset-version:{self.source_identity.source_id}@"
            f"{self.version_identity.repository_version}",
            f"verified-raw-artifact:{self.raw_row_identity.raw_artifact_sha256}",
            None,
            None,
            f"source-row:{self.raw_row_identity.source_row_number}",
            f"mapping-version:{self.mapping_version}",
            f"canonical-record:{expected_canonical_id}",
        )
        if len(self.lineage) != len(expected_lineage):
            raise ValueError("canonical record lineage must contain the complete eight-step chain")
        if any(
            expected is not None and actual != expected
            for actual, expected in zip(self.lineage, expected_lineage, strict=True)
        ):
            raise ValueError("canonical record lineage does not match its source identity")
        if not self.lineage[3].startswith("acquisition-receipt:"):
            raise ValueError("canonical record lineage must identify an acquisition receipt")
        if not self.lineage[4].startswith("source-schema:"):
            raise ValueError("canonical record lineage must identify a source schema")
        if self.variable_identity.resolution_status in (
            VariableResolutionStatus.UNRESOLVED,
            VariableResolutionStatus.QUARANTINED,
        ):
            raise ValueError("unresolved source variables cannot enter canonical records")

    @property
    def source(self) -> DatasetSourceIdentity:
        return self.source_identity

    @property
    def version(self) -> DatasetVersionIdentity:
        return self.version_identity

    @property
    def raw_artifact_sha256(self) -> str:
        return self.raw_row_identity.raw_artifact_sha256

    @property
    def source_row_number(self) -> int:
        return self.raw_row_identity.source_row_number


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalEmpiricalArtifactReceipt:
    """Deterministic receipt for a full canonical JSONL artifact."""

    source_id: str
    source_version: str
    raw_source_sha256: str
    canonical_artifact_sha256: str
    canonical_record_count: int
    mapping_version: str
    relative_path: str
    metadata_snapshot_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        object.__setattr__(
            self, "raw_source_sha256", _digest(self.raw_source_sha256, "raw_source_sha256")
        )
        object.__setattr__(
            self,
            "canonical_artifact_sha256",
            _digest(self.canonical_artifact_sha256, "canonical_artifact_sha256"),
        )
        _nonnegative_int(self.canonical_record_count, "canonical_record_count")
        _require_text(self.mapping_version, "mapping_version")
        _relative_path(self.relative_path, "relative_path")
        object.__setattr__(
            self,
            "metadata_snapshot_sha256",
            _optional_digest(self.metadata_snapshot_sha256, "metadata_snapshot_sha256"),
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """The sole deterministic conjunctive promotion authority."""

    decision_id: ScientificIdentifier
    status: PromotionStatus
    can_promote: bool
    runtime_integrity_pass: bool
    source_qualified: bool
    population_qualified: bool
    raw_bytes_verified: bool
    source_version_verified: bool
    license_captured: bool
    variable_identity_resolved: bool
    football_world_mapping_resolved: bool
    lineage_complete: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.decision_id, ScientificIdentifier, "decision_id")
        _require_enum(self.status, PromotionStatus, "status")
        flags = (
            self.runtime_integrity_pass,
            self.source_qualified,
            self.population_qualified,
            self.raw_bytes_verified,
            self.source_version_verified,
            self.license_captured,
            self.variable_identity_resolved,
            self.football_world_mapping_resolved,
            self.lineage_complete,
        )
        if any(not isinstance(flag, bool) for flag in flags) or not isinstance(
            self.can_promote,
            bool,
        ):
            raise ValueError("promotion gates must be booleans")
        expected = all(flags)
        if self.can_promote is not expected:
            raise ValueError("can_promote must equal the deterministic gate conjunction")
        expected_status = PromotionStatus.PROMOTED if expected else self.status
        if expected and self.status is not PromotionStatus.PROMOTED:
            raise ValueError("a passing promotion decision must be PROMOTED")
        if not expected and self.status is PromotionStatus.PROMOTED:
            raise ValueError("a failing promotion decision cannot be PROMOTED")
        if expected_status is PromotionStatus.PROMOTED and self.reason_codes:
            raise ValueError("a promoted decision cannot carry failure reason codes")
        _text_tuple(self.reason_codes, "reason_codes")

    @property
    def promoted(self) -> bool:
        return self.can_promote


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceVersionConflict:
    """Receipt for a registered version whose exact bytes changed."""

    source_id: str
    source_version: str
    expected_sha256: str
    actual_sha256: str
    expected_byte_size: int | None = None
    actual_byte_size: int | None = None
    reason_code: str = "SOURCE_VERSION_CONFLICT"

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        object.__setattr__(
            self, "expected_sha256", _digest(self.expected_sha256, "expected_sha256")
        )
        object.__setattr__(self, "actual_sha256", _digest(self.actual_sha256, "actual_sha256"))
        if self.expected_sha256 == self.actual_sha256:
            raise ValueError("a source version conflict requires different digests")
        for field_name, value in (
            ("expected_byte_size", self.expected_byte_size),
            ("actual_byte_size", self.actual_byte_size),
        ):
            if value is not None:
                _nonnegative_int(value, field_name)
        _require_text(self.reason_code, "reason_code")


# Readable aliases for callers using the wording in the specification.
DatasetLicense = DatasetLicenseIdentity
CanonicalEmpiricalContext = CanonicalFootballContext


__all__ = [
    "ArtifactAcquisitionReceipt",
    "CanonicalEmpiricalArtifactReceipt",
    "CanonicalEmpiricalContext",
    "CanonicalEmpiricalRecord",
    "CanonicalFootballContext",
    "DatasetLicense",
    "DatasetLicenseIdentity",
    "DatasetQualificationReceipt",
    "DatasetQualificationStatus",
    "DatasetSourceIdentity",
    "DatasetVersionIdentity",
    "JSONScalar",
    "PromotionDecision",
    "PromotionStatus",
    "QuarantineReceipt",
    "RawRowIdentity",
    "SourceMetadataClaim",
    "SourceMetadataConflict",
    "SourceSchema",
    "SourceVariableIdentity",
    "SourceVariableRole",
    "SourceVersionConflict",
    "VariableResolutionStatus",
    "VerifiedRawArtifact",
    "WorkbookSchema",
    "WorkbookSheetSchema",
]
