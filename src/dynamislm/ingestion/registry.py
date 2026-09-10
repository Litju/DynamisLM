"""Committed public metadata registry for RES-63 source identities."""

from __future__ import annotations

import datetime as datetime_module
import json
from pathlib import Path
from typing import Any, cast

from dynamislm.ingestion.contracts import (
    DatasetLicenseIdentity,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
)

REGISTRY_RELATIVE_ROOT = Path("registries") / "datasets"
_FORBIDDEN_REGISTRY_KEYS = frozenset(
    {"raw_rows", "canonical_rows", "athlete_rows", "dob_table", "credentials"}
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def registry_root(repository_root: Path | None = None) -> Path:
    return (repository_root or _repository_root()) / REGISTRY_RELATIVE_ROOT


def _assert_public_metadata(value: object, key_path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_REGISTRY_KEYS:
                raise ValueError(f"registry contains forbidden data field: {key_path}{key}")
            _assert_public_metadata(item, f"{key_path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_metadata(item, f"{key_path}[{index}].")
    elif isinstance(value, str):
        if value.startswith("/") or value.startswith("~") or value.startswith("\\"):
            raise ValueError("registry must not contain resolved local paths")


def load_dataset_registry(
    source_id: str,
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Load one committed source registry record without loading athlete rows."""

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must not be empty")
    if Path(source_id).name != source_id or source_id in {".", ".."}:
        raise ValueError("source_id must be a single registry filename component")
    path = registry_root(repository_root) / f"{source_id}.json"
    if not path.is_file():
        versioned_path = registry_root(repository_root) / f"{source_id}-v1.json"
        if versioned_path.is_file():
            path = versioned_path
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid dataset registry document: {path.name}") from exc
    if not isinstance(document, dict):
        raise ValueError("dataset registry document must be an object")
    _assert_public_metadata(document)
    if document.get("source_id") != source_id:
        raise ValueError("dataset registry source_id does not match filename/request")
    return cast(dict[str, Any], document)


def load_all_dataset_registries(
    *,
    repository_root: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Load all committed registry documents in stable filename order."""

    documents: list[dict[str, Any]] = []
    for path in sorted(registry_root(repository_root).glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"registry document must be an object: {path.name}")
        _assert_public_metadata(document)
        documents.append(cast(dict[str, Any], document))
    return tuple(documents)


def _mapping(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"registry field {key!r} must be an object")
    return value


def _required_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"registry field {key!r} must be a non-empty string")
    return value


def _optional_string(document: dict[str, Any], key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"registry field {key!r} must be a non-empty string when present")
    return value


def dataset_source_identity(document: dict[str, Any]) -> DatasetSourceIdentity:
    """Build a typed source identity from one registry document."""

    return DatasetSourceIdentity(
        source_id=_required_string(document, "source_id"),
        provider=_required_string(document, "provider"),
        title=_required_string(document, "title"),
        landing_page_uri=_required_string(document, "landing_page_uri"),
        persistent_identifier=_required_string(document, "persistent_identifier"),
    )


def dataset_version_identity(document: dict[str, Any]) -> DatasetVersionIdentity:
    """Build a typed source-version identity from one registry document."""

    version = _mapping(document, "version")
    published_at = version.get("published_at")
    published_value: datetime_module.date | datetime_module.datetime | None
    if isinstance(published_at, str):
        published_value = (
            datetime_module.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if "T" in published_at
            else datetime_module.date.fromisoformat(published_at)
        )
    else:
        published_value = None
    return DatasetVersionIdentity(
        repository_version=_required_string(version, "repository_version"),
        version_specific_persistent_identifier=_optional_string(
            version,
            "version_specific_persistent_identifier",
        ),
        published_at=published_value,
    )


def dataset_license_identity(document: dict[str, Any]) -> DatasetLicenseIdentity:
    """Build the deliberately small machine-readable license identity."""

    license_document = _mapping(document, "license")
    attribution_required = license_document.get("attribution_required")
    noncommercial_restriction = license_document.get("noncommercial_restriction")
    if not isinstance(attribution_required, bool) or not isinstance(
        noncommercial_restriction,
        bool,
    ):
        raise ValueError("registry license flags must be booleans")
    return DatasetLicenseIdentity(
        spdx_expression=_required_string(license_document, "spdx_expression"),
        canonical_uri=_required_string(license_document, "canonical_uri"),
        assertion_source_uri=_required_string(license_document, "assertion_source_uri"),
        attribution_required=attribution_required,
        noncommercial_restriction=noncommercial_restriction,
        notes=(
            str(license_document["notes"]) if license_document.get("notes") is not None else None
        ),
    )


def registry_file_entries(document: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return public file identities in the deterministic registry order."""

    files = document.get("files", ())
    if not isinstance(files, list):
        raise ValueError("registry files must be an array")
    entries: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("registry file entries must be objects")
        entries.append(cast(dict[str, Any], item))
    return tuple(entries)


# Short aliases used by operational callers.
load_registry = load_dataset_registry
source_identity_from_registry = dataset_source_identity
version_identity_from_registry = dataset_version_identity
license_identity_from_registry = dataset_license_identity


__all__ = [
    "REGISTRY_RELATIVE_ROOT",
    "dataset_license_identity",
    "dataset_source_identity",
    "dataset_version_identity",
    "license_identity_from_registry",
    "load_all_dataset_registries",
    "load_dataset_registry",
    "load_registry",
    "registry_file_entries",
    "registry_root",
    "source_identity_from_registry",
    "version_identity_from_registry",
]
