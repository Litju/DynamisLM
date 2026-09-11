"""Immutable contracts for the RES-63 dataset-ingestion boundary.

These objects describe source identity, byte integrity, qualification, mapping,
and the narrow empirical intermediate used before any RES-64 computation.  A
source-reported value remains an external observation; it is not a
DynamisLM-derived measurement result.
"""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

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
from dynamislm.serialization import canonical_hash, register_serializable_type

type JSONScalar = str | int | float | bool | None

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_RELATIVE_PATH_PREFIXES = ("objects/", "metadata/", "receipts/", "canonical/", "quarantine/")
_EMPTY_SHA256 = f"sha256:{hashlib.sha256(b'').hexdigest()}"


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
    if "\\" in value:
        raise ValueError(f"{field_name} must be a repository-external relative path")
    normalized = PurePosixPath(value).as_posix()
    if value != normalized or PurePosixPath(value).is_absolute():
        raise ValueError(f"{field_name} must be a canonical relative POSIX path")
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        raise ValueError(f"{field_name} must not contain traversal segments")
    if not PurePosixPath(value).parts or PurePosixPath(value).parts[0] not in {
        prefix[:-1] for prefix in _RELATIVE_PATH_PREFIXES
    }:
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


class FileRepresentation(StrEnum):
    """Identity of the exact provider representation being handled."""

    PROVIDER_FILE = "PROVIDER_FILE"
    ARCHIVAL_TAB = "ARCHIVAL_TAB"
    SAVED_ORIGINAL = "SAVED_ORIGINAL"


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
class RegisteredDatasetFileIdentity:
    """Registry-anchored file identity; live provider state cannot populate it."""

    source_id: str
    source_version: str
    representation: FileRepresentation
    filename: str
    media_type: str
    expected_sha256: str
    expected_byte_size: int
    provider_file_id: str | int | None = None
    file_persistent_identifier: str | None = None
    provider_hash: str | None = None
    provider_hash_algorithm: str | None = None
    provider_declared_byte_size: int | None = None
    provider_hash_representation: FileRepresentation | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("filename", self.filename),
            ("media_type", self.media_type),
        ):
            _require_text(value, field_name)
        _require_enum(self.representation, FileRepresentation, "representation")
        object.__setattr__(
            self,
            "expected_sha256",
            _digest(self.expected_sha256, "expected_sha256"),
        )
        _nonnegative_int(self.expected_byte_size, "expected_byte_size")
        if self.provider_file_id is not None:
            if isinstance(self.provider_file_id, bool) or not isinstance(
                self.provider_file_id, str | int
            ):
                raise ValueError("provider_file_id must be a string, integer, or None")
            if isinstance(self.provider_file_id, str):
                _require_text(self.provider_file_id, "provider_file_id")
        if self.file_persistent_identifier is not None:
            _require_text(self.file_persistent_identifier, "file_persistent_identifier")
        if self.provider_hash is not None:
            _require_text(self.provider_hash, "provider_hash")
            if self.provider_hash_algorithm is None:
                raise ValueError("provider_hash_algorithm is required with provider_hash")
        if self.provider_hash_algorithm is not None:
            _require_text(self.provider_hash_algorithm, "provider_hash_algorithm")
        if self.provider_declared_byte_size is not None:
            _nonnegative_int(self.provider_declared_byte_size, "provider_declared_byte_size")
        if self.provider_hash_representation is not None:
            _require_enum(
                self.provider_hash_representation,
                FileRepresentation,
                "provider_hash_representation",
            )

    @property
    def file_id(self) -> str | int | None:
        return self.provider_file_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SavedOriginalVerificationReceipt:
    """Streamed observation of a provider's saved-original representation.

    The receipt contains observations only.  Its validity is established by
    checking the observed values against the registered file identity and the
    exact persisted metadata snapshot; no stored success flag is authoritative.
    """

    source_id: str
    source_version: str
    provider_file_id: str | int
    file_persistent_identifier: str
    representation: FileRepresentation
    provider_hash_algorithm: str
    provider_hash: str
    observed_md5: str
    observed_sha256: str
    observed_byte_size: int
    metadata_snapshot_sha256: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("file_persistent_identifier", self.file_persistent_identifier),
            ("provider_hash_algorithm", self.provider_hash_algorithm),
            ("provider_hash", self.provider_hash),
            ("observed_md5", self.observed_md5),
        ):
            _require_text(value, field_name)
        if isinstance(self.provider_file_id, bool) or not isinstance(
            self.provider_file_id, str | int
        ):
            raise ValueError("provider_file_id must be a string or integer")
        if isinstance(self.provider_file_id, str):
            _require_text(self.provider_file_id, "provider_file_id")
        _require_enum(self.representation, FileRepresentation, "representation")
        if self.representation is not FileRepresentation.SAVED_ORIGINAL:
            raise ValueError("saved-original verification must identify SAVED_ORIGINAL")
        if self.provider_hash_algorithm.lower() != "md5":
            raise ValueError("saved-original provider hash algorithm must be md5")
        if _MD5_RE.fullmatch(self.provider_hash) is None:
            raise ValueError("provider_hash must be an MD5 hexadecimal value")
        if _MD5_RE.fullmatch(self.observed_md5) is None:
            raise ValueError("observed_md5 must be an MD5 hexadecimal value")
        if self.provider_hash.lower() != self.observed_md5.lower():
            raise ValueError("observed_md5 does not match provider_hash")
        object.__setattr__(
            self,
            "observed_sha256",
            _digest(self.observed_sha256, "observed_sha256"),
        )
        _nonnegative_int(self.observed_byte_size, "observed_byte_size")
        object.__setattr__(
            self,
            "metadata_snapshot_sha256",
            _digest(self.metadata_snapshot_sha256, "metadata_snapshot_sha256"),
        )


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
        supported = {
            "CC-BY-4.0": (
                "https://creativecommons.org/licenses/by/4.0/",
                True,
                False,
            ),
            "CC-BY-NC-4.0": (
                "https://creativecommons.org/licenses/by-nc/4.0/",
                True,
                True,
            ),
        }
        _require_text(self.spdx_expression, "spdx_expression")
        expected = supported.get(self.spdx_expression)
        if expected is None:
            raise ValueError("unsupported license SPDX expression")
        _require_text(self.canonical_uri, "canonical_uri")
        _require_text(self.assertion_source_uri, "assertion_source_uri")
        if not isinstance(self.attribution_required, bool):
            raise ValueError("attribution_required must be a boolean")
        if not isinstance(self.noncommercial_restriction, bool):
            raise ValueError("noncommercial_restriction must be a boolean")
        if (
            self.attribution_required is not expected[1]
            or self.noncommercial_restriction is not expected[2]
        ):
            raise ValueError("license restriction flags do not match SPDX expression")
        if self.canonical_uri != expected[0]:
            raise ValueError("license canonical URI does not match SPDX expression")
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
    representation: FileRepresentation = FileRepresentation.PROVIDER_FILE
    provider_file_id: str | int | None = None

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
        _require_enum(self.representation, FileRepresentation, "representation")
        if self.provider_file_id is not None:
            if isinstance(self.provider_file_id, bool) or not isinstance(
                self.provider_file_id, str | int
            ):
                raise ValueError("provider_file_id must be a string, integer, or None")
            if isinstance(self.provider_file_id, str):
                _require_text(self.provider_file_id, "provider_file_id")
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
    representation: FileRepresentation = FileRepresentation.PROVIDER_FILE

    def __post_init__(self) -> None:
        _require_instance(self.artifact_id, InstanceIdentifier, "artifact_id")
        if self.artifact_id.instance_type != "artifact":
            raise ValueError("artifact_id must identify an artifact")
        object.__setattr__(self, "sha256", _digest(self.sha256, "sha256"))
        if self.artifact_id.value != self.sha256:
            raise ValueError("artifact_id must be content-derived from sha256")
        _nonnegative_int(self.byte_size, "byte_size")
        _require_text(self.media_type, "media_type")
        _relative_path(self.relative_path, "relative_path")
        _require_instance(
            self.acquisition_receipt,
            ArtifactAcquisitionReceipt,
            "acquisition_receipt",
        )
        _require_enum(self.representation, FileRepresentation, "representation")
        if self.acquisition_receipt.representation is not self.representation:
            raise ValueError("artifact representation must match acquisition receipt")
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
class SourceVersionVerificationReceipt:
    """Derived proof that one verified artifact matches its registered file."""

    registered_file_identity: RegisteredDatasetFileIdentity
    verified_artifact: VerifiedRawArtifact

    def __post_init__(self) -> None:
        _require_instance(
            self.registered_file_identity,
            RegisteredDatasetFileIdentity,
            "registered_file_identity",
        )
        _require_instance(self.verified_artifact, VerifiedRawArtifact, "verified_artifact")
        registered = self.registered_file_identity
        artifact = self.verified_artifact
        receipt = artifact.acquisition_receipt
        if receipt.source_id != registered.source_id:
            raise ValueError("registered source ID does not match verified artifact")
        if receipt.source_version != registered.source_version:
            raise ValueError("registered source version does not match verified artifact")
        if artifact.representation is not registered.representation:
            raise ValueError("registered representation does not match verified artifact")
        if artifact.sha256 != registered.expected_sha256:
            raise ValueError("verified artifact SHA-256 does not match registered identity")
        if artifact.byte_size != registered.expected_byte_size:
            raise ValueError("verified artifact byte size does not match registered identity")
        if artifact.acquisition_receipt.original_filename != registered.filename:
            raise ValueError("verified filename does not match registered identity")
        if artifact.acquisition_receipt.media_type != registered.media_type:
            raise ValueError("verified media type does not match registered identity")
        if (
            registered.provider_file_id is not None
            and receipt.provider_file_id != registered.provider_file_id
        ):
            raise ValueError("verified provider file ID does not match registered identity")

    @property
    def verified(self) -> bool:
        """Compatibility/readability property derived from successful construction."""

        return True

    @property
    def source_id(self) -> str:
        return self.registered_file_identity.source_id

    @property
    def source_version(self) -> str:
        return self.registered_file_identity.source_version

    @property
    def representation(self) -> FileRepresentation:
        return self.registered_file_identity.representation


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


def stable_source_variable_id(identity: SourceVariableIdentity) -> str:
    """Return the stable content-derived ID used by compact canonical rows."""

    _require_instance(identity, SourceVariableIdentity, "identity")
    return f"source-variable:{canonical_hash(identity).removeprefix('sha256:')}"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceVariableRegistryEntry:
    """One complete source-variable identity stored outside repeated row payloads."""

    variable_id: str
    identity: SourceVariableIdentity

    def __post_init__(self) -> None:
        _require_text(self.variable_id, "variable_id")
        _require_instance(self.identity, SourceVariableIdentity, "identity")
        expected = stable_source_variable_id(self.identity)
        if self.variable_id != expected:
            raise ValueError("variable_id must be content-derived from identity")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceVariableRegistry:
    """Deterministic ordered registry of complete source-variable identities."""

    source_id: str
    source_version: str
    mapping_version: str
    entries: tuple[SourceVariableRegistryEntry, ...]

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_version, "source_version")
        _require_text(self.mapping_version, "mapping_version")
        _require_tuple_items(self.entries, SourceVariableRegistryEntry, "entries")
        ids = tuple(entry.variable_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise ValueError("source variable registry IDs must be unique")
        identities = tuple(entry.identity.original_column_name for entry in self.entries)
        if len(set(identities)) != len(identities):
            raise ValueError("source variable registry columns must be unique")

    @property
    def sha256(self) -> str:
        return canonical_hash(self)

    @property
    def variable_ids(self) -> tuple[str, ...]:
        return tuple(entry.variable_id for entry in self.entries)

    def entry_for(self, identity: SourceVariableIdentity) -> SourceVariableRegistryEntry:
        variable_id = stable_source_variable_id(identity)
        for entry in self.entries:
            if entry.variable_id == variable_id and entry.identity == identity:
                return entry
        raise ValueError("source variable is not present in the registry")


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
    license_identity: DatasetLicenseIdentity | None = None
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
        if self.license_identity is not None:
            _require_instance(self.license_identity, DatasetLicenseIdentity, "license_identity")
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
        if self.status is DatasetQualificationStatus.QUALIFIED:
            if self.population_decision is None or not self.population_decision.passed:
                raise ValueError("QUALIFIED receipt requires a passing population decision")
            if self.source_decision is None or not self.source_decision.passed:
                raise ValueError("QUALIFIED receipt requires a passing source decision")
            if self.source_decision.population_decision != self.population_decision:
                raise ValueError("QUALIFIED receipt source and population decisions differ")
            if self.source_decision.source.source_id.identifier.key != self.source_id:
                raise ValueError("QUALIFIED receipt source decision is bound to another source")
            if self.source_decision.source.source_revision != self.source_version:
                raise ValueError("QUALIFIED receipt source decision is bound to another version")
            if self.artifact_sha256 is None:
                raise ValueError("QUALIFIED receipt requires artifact_sha256")
            if self.evidence_class is not EvidenceClass.CANONICAL_EMPIRICAL_TARGET:
                raise ValueError("QUALIFIED receipt requires canonical empirical evidence")
            if self.license_identity is None:
                raise ValueError("QUALIFIED receipt requires license_identity")
            if self.variable_identity_status is not VariableResolutionStatus.RESOLVED:
                raise ValueError("QUALIFIED receipt requires resolved variable identities")
            if self.football_mapping_status is not VariableResolutionStatus.RESOLVED:
                raise ValueError("QUALIFIED receipt requires resolved football mapping")
            if self.reason_codes != () or self.missing_information != ():
                raise ValueError("QUALIFIED receipt cannot contain failure reasons")
        else:
            if self.evidence_class is EvidenceClass.CANONICAL_EMPIRICAL_TARGET:
                raise ValueError("non-qualified receipt cannot claim canonical evidence")
            if not self.reason_codes and not self.missing_information:
                raise ValueError("non-qualified receipt requires a failure reason or missing data")

    @property
    def actual_observed_data(self) -> bool:
        return bool(
            self.source_decision is not None
            and any(
                requirement.requirement.value == "ACTUAL_OBSERVED_DATA"
                and requirement.status.value == "PASS"
                for requirement in self.source_decision.requirements
            )
        )

    @property
    def performance_science_relevance(self) -> bool:
        return self.actual_observed_data and self.source_decision is not None

    @property
    def license_captured(self) -> bool:
        return self.license_identity is not None


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
    variable_registry_sha256: str | None = None
    variable_registry_relative_path: str | None = None

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
        object.__setattr__(
            self,
            "variable_registry_sha256",
            _optional_digest(self.variable_registry_sha256, "variable_registry_sha256"),
        )
        if self.variable_registry_relative_path is not None:
            _relative_path(self.variable_registry_relative_path, "variable_registry_relative_path")


RES63_RUNTIME_AUTHORITY_ID = "dynamislm:res63-runtime-authority@1.0.0"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RuntimeAuthorityIdentity:
    """Fixed internal RES-63 runtime authority identity."""

    authority_id: str = RES63_RUNTIME_AUTHORITY_ID

    def __post_init__(self) -> None:
        _require_text(self.authority_id, "authority_id")
        if self.authority_id != RES63_RUNTIME_AUTHORITY_ID:
            raise ValueError("runtime authority identity is not the fixed RES-63 authority")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalValidationReceipt:
    """Derived validation evidence for the exact compact canonical stream."""

    source_id: str
    source_version: str
    raw_source_sha256: str
    mapping_version: str
    canonical_artifact_sha256: str
    canonical_record_count: int
    variable_registry_sha256: str
    included_variable_ids: tuple[str, ...]
    record_lineage_digest: str
    football_context_digest: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("mapping_version", self.mapping_version),
        ):
            _require_text(value, field_name)
        object.__setattr__(
            self,
            "raw_source_sha256",
            _digest(self.raw_source_sha256, "raw_source_sha256"),
        )
        object.__setattr__(
            self,
            "canonical_artifact_sha256",
            _digest(self.canonical_artifact_sha256, "canonical_artifact_sha256"),
        )
        _nonnegative_int(self.canonical_record_count, "canonical_record_count")
        object.__setattr__(
            self,
            "variable_registry_sha256",
            _digest(self.variable_registry_sha256, "variable_registry_sha256"),
        )
        _text_tuple(self.included_variable_ids, "included_variable_ids")
        object.__setattr__(
            self,
            "record_lineage_digest",
            _digest(self.record_lineage_digest, "record_lineage_digest"),
        )
        object.__setattr__(
            self,
            "football_context_digest",
            _digest(self.football_context_digest, "football_context_digest"),
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    """Typed evidence tree from which every promotion gate is derived."""

    qualification: DatasetQualificationReceipt
    registered_file_identity: RegisteredDatasetFileIdentity
    verified_raw_artifact: VerifiedRawArtifact
    source_version_verification: SourceVersionVerificationReceipt
    license_identity: DatasetLicenseIdentity
    variable_registry: SourceVariableRegistry
    canonical_validation: CanonicalValidationReceipt
    runtime_authority: RuntimeAuthorityIdentity

    def __post_init__(self) -> None:
        _require_instance(self.qualification, DatasetQualificationReceipt, "qualification")
        _require_instance(
            self.registered_file_identity,
            RegisteredDatasetFileIdentity,
            "registered_file_identity",
        )
        _require_instance(self.verified_raw_artifact, VerifiedRawArtifact, "verified_raw_artifact")
        _require_instance(
            self.source_version_verification,
            SourceVersionVerificationReceipt,
            "source_version_verification",
        )
        _require_instance(self.license_identity, DatasetLicenseIdentity, "license_identity")
        _require_instance(self.variable_registry, SourceVariableRegistry, "variable_registry")
        _require_instance(
            self.canonical_validation,
            CanonicalValidationReceipt,
            "canonical_validation",
        )
        _require_instance(self.runtime_authority, RuntimeAuthorityIdentity, "runtime_authority")
        registered = self.registered_file_identity
        artifact = self.verified_raw_artifact
        receipt = self.source_version_verification
        if receipt.registered_file_identity != registered or receipt.verified_artifact != artifact:
            raise ValueError("promotion evidence contains inconsistent source-version evidence")
        if self.qualification.source_id != registered.source_id:
            raise ValueError("promotion qualification source does not match registered identity")
        if self.qualification.source_version != registered.source_version:
            raise ValueError("promotion qualification version does not match registered identity")
        if self.qualification.artifact_sha256 != registered.expected_sha256:
            raise ValueError("promotion qualification artifact does not match registered identity")
        if artifact.sha256 != registered.expected_sha256:
            raise ValueError("promotion raw artifact SHA-256 does not match registered identity")
        if artifact.byte_size != registered.expected_byte_size:
            raise ValueError("promotion raw artifact byte size does not match registered identity")
        if (
            self.qualification.source_decision is None
            or self.qualification.source_decision.source.source_id.identifier.key
            != registered.source_id
        ):
            raise ValueError("promotion source decision source does not match registered identity")
        if (
            self.qualification.source_decision is None
            or self.qualification.source_decision.source.source_revision
            != registered.source_version
        ):
            raise ValueError("promotion source decision version does not match registered identity")
        if (
            self.qualification.source_decision is None
            or self.qualification.source_decision.population_decision
            != self.qualification.population_decision
        ):
            raise ValueError("promotion source and qualification population decisions differ")
        validation = self.canonical_validation
        if validation.source_id != registered.source_id:
            raise ValueError("canonical validation source does not match registered identity")
        if validation.source_version != registered.source_version:
            raise ValueError("canonical validation version does not match registered identity")
        if validation.raw_source_sha256 != registered.expected_sha256:
            raise ValueError("canonical validation raw digest does not match registered identity")
        if validation.variable_registry_sha256 != self.variable_registry.sha256:
            raise ValueError(
                "canonical validation variable registry digest does not match evidence"
            )
        if validation.mapping_version != self.variable_registry.mapping_version:
            raise ValueError("canonical validation mapping does not match variable registry")
        if validation.source_id != self.variable_registry.source_id:
            raise ValueError("canonical validation source does not match variable registry")
        if validation.source_version != self.variable_registry.source_version:
            raise ValueError("canonical validation version does not match variable registry")
        if self.variable_registry.source_id != registered.source_id:
            raise ValueError("variable registry source does not match registered identity")
        if self.variable_registry.source_version != registered.source_version:
            raise ValueError("variable registry version does not match registered identity")
        if self.qualification.license_identity != self.license_identity:
            raise ValueError("promotion license evidence does not match qualification")


def _promotion_gate_results(evidence: PromotionEvidence) -> tuple[tuple[str, bool], ...]:
    qualification = evidence.qualification
    source_decision = qualification.source_decision
    population_decision = qualification.population_decision
    validation = evidence.canonical_validation
    registry_ids = set(evidence.variable_registry.variable_ids)
    included_ids = set(validation.included_variable_ids)
    included_entries = tuple(
        entry for entry in evidence.variable_registry.entries if entry.variable_id in included_ids
    )
    registry_resolved = (not included_ids and validation.canonical_record_count == 0) or (
        bool(included_entries)
        and all(
            entry.identity.resolution_status
            not in (VariableResolutionStatus.UNRESOLVED, VariableResolutionStatus.QUARANTINED)
            for entry in included_entries
        )
    )
    source_qualified = bool(
        qualification.status is DatasetQualificationStatus.QUALIFIED
        and source_decision is not None
        and source_decision.passed
        and qualification.actual_observed_data
        and qualification.source_id == evidence.registered_file_identity.source_id
        and qualification.source_version == evidence.registered_file_identity.source_version
        and source_decision.source.source_id.identifier.key == qualification.source_id
        and source_decision.source.source_revision == qualification.source_version
        and source_decision.population_decision == population_decision
        and qualification.artifact_sha256 == evidence.registered_file_identity.expected_sha256
        and qualification.evidence_class is EvidenceClass.CANONICAL_EMPIRICAL_TARGET
        and qualification.license_identity == evidence.license_identity
        and qualification.variable_identity_status is VariableResolutionStatus.RESOLVED
        and qualification.football_mapping_status is VariableResolutionStatus.RESOLVED
        and qualification.reason_codes == ()
        and qualification.missing_information == ()
    )
    population_qualified = bool(
        population_decision is not None
        and population_decision.passed
        and source_decision is not None
        and source_decision.passed
        and source_decision.population_decision == population_decision
    )
    raw_bytes_verified = bool(
        evidence.verified_raw_artifact.sha256 == evidence.registered_file_identity.expected_sha256
        and evidence.verified_raw_artifact.byte_size
        == evidence.registered_file_identity.expected_byte_size
        and qualification.artifact_sha256 == evidence.registered_file_identity.expected_sha256
        and qualification.artifact_sha256 == evidence.verified_raw_artifact.sha256
    )
    source_version_verified = evidence.source_version_verification.verified
    license_captured = bool(
        qualification.license_identity == evidence.license_identity
        and evidence.license_identity.spdx_expression in {"CC-BY-4.0", "CC-BY-NC-4.0"}
    )
    variable_identity_resolved = bool(
        qualification.variable_identity_status is VariableResolutionStatus.RESOLVED
        and (validation.canonical_record_count == 0 or bool(validation.included_variable_ids))
        and included_ids <= registry_ids
        and registry_resolved
        and validation.mapping_version == evidence.variable_registry.mapping_version
    )
    football_world_mapping_resolved = bool(
        qualification.football_mapping_status is VariableResolutionStatus.RESOLVED
        and validation.canonical_record_count > 0
        and validation.football_context_digest != _EMPTY_SHA256
    )
    lineage_complete = bool(
        validation.record_lineage_digest and validation.canonical_record_count > 0
    )
    runtime_integrity = evidence.runtime_authority.authority_id == RES63_RUNTIME_AUTHORITY_ID
    return (
        ("RUNTIME_INTEGRITY", runtime_integrity),
        ("SOURCE_QUALIFIED", source_qualified),
        ("POPULATION_QUALIFIED", population_qualified),
        ("RAW_BYTES_VERIFIED", raw_bytes_verified),
        ("SOURCE_VERSION_VERIFIED", source_version_verified),
        ("LICENSE_CAPTURED", license_captured),
        ("VARIABLE_IDENTITY_RESOLVED", variable_identity_resolved),
        ("FOOTBALL_WORLD_MAPPING_RESOLVED", football_world_mapping_resolved),
        ("LINEAGE_COMPLETE", lineage_complete),
    )


def _promotion_decision_material(evidence: PromotionEvidence) -> dict[str, object]:
    """Select stable evidence fields; acquisition timestamps are not decision authority."""

    registered = evidence.registered_file_identity
    artifact = evidence.verified_raw_artifact
    return {
        "qualification": evidence.qualification,
        "registered_file_identity": registered,
        "verified_raw_artifact": {
            "sha256": artifact.sha256,
            "byte_size": artifact.byte_size,
            "media_type": artifact.media_type,
            "relative_path": artifact.relative_path,
            "representation": artifact.representation,
        },
        "source_version_verification": {
            "source_id": evidence.source_version_verification.source_id,
            "source_version": evidence.source_version_verification.source_version,
            "representation": evidence.source_version_verification.representation,
            "expected_sha256": registered.expected_sha256,
            "expected_byte_size": registered.expected_byte_size,
            "provider_file_id": registered.provider_file_id,
        },
        "license_identity": evidence.license_identity,
        "variable_registry": evidence.variable_registry,
        "canonical_validation": evidence.canonical_validation,
        "runtime_authority": evidence.runtime_authority,
    }


def promotion_gate_results(evidence: PromotionEvidence) -> tuple[tuple[str, bool], ...]:
    """Derive promotion gates from typed evidence; no caller truth is accepted."""

    _require_instance(evidence, PromotionEvidence, "evidence")
    return _promotion_gate_results(evidence)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Immutable decision record; operational authority lives in promotion_from_evidence."""

    decision_id: ScientificIdentifier
    status: PromotionStatus
    reason_codes: tuple[str, ...]
    evidence: PromotionEvidence

    def __post_init__(self) -> None:
        _require_instance(self.decision_id, ScientificIdentifier, "decision_id")
        _require_enum(self.status, PromotionStatus, "status")
        _require_instance(self.evidence, PromotionEvidence, "evidence")
        _text_tuple(self.reason_codes, "reason_codes")
        gates = _promotion_gate_results(self.evidence)
        passed = all(value for _, value in gates)
        expected_status = PromotionStatus.PROMOTED if passed else PromotionStatus.QUARANTINED
        expected_reasons = tuple(f"{name}_FAILED" for name, value in gates if not value)
        if self.status is not expected_status:
            raise ValueError("promotion status does not match derived evidence")
        if self.reason_codes != expected_reasons:
            raise ValueError("promotion reason codes do not match derived evidence")
        decision_key = canonical_hash(
            {"evidence": _promotion_decision_material(self.evidence), "gates": gates}
        ).removeprefix("sha256:")
        expected_id = ScientificIdentifier(
            "dynamislm",
            "promotion-decision",
            decision_key,
            "1.1.0",
        )
        if self.decision_id != expected_id:
            raise ValueError("promotion decision ID does not match derived evidence")

    @property
    def can_promote(self) -> bool:
        return self.status is PromotionStatus.PROMOTED

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
    "RES63_RUNTIME_AUTHORITY_ID",
    "ArtifactAcquisitionReceipt",
    "CanonicalEmpiricalArtifactReceipt",
    "CanonicalEmpiricalContext",
    "CanonicalEmpiricalRecord",
    "CanonicalFootballContext",
    "CanonicalValidationReceipt",
    "DatasetLicense",
    "DatasetLicenseIdentity",
    "DatasetQualificationReceipt",
    "DatasetQualificationStatus",
    "DatasetSourceIdentity",
    "DatasetVersionIdentity",
    "FileRepresentation",
    "JSONScalar",
    "PromotionDecision",
    "PromotionEvidence",
    "PromotionStatus",
    "QuarantineReceipt",
    "RawRowIdentity",
    "RegisteredDatasetFileIdentity",
    "RuntimeAuthorityIdentity",
    "SavedOriginalVerificationReceipt",
    "SourceMetadataClaim",
    "SourceMetadataConflict",
    "SourceSchema",
    "SourceVariableIdentity",
    "SourceVariableRegistry",
    "SourceVariableRegistryEntry",
    "SourceVariableRole",
    "SourceVersionConflict",
    "SourceVersionVerificationReceipt",
    "VariableResolutionStatus",
    "VerifiedRawArtifact",
    "WorkbookSchema",
    "WorkbookSheetSchema",
    "stable_source_variable_id",
]
