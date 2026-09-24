"""Deterministic resolution of accepted RES-115 JATS evidence artifacts.

The core pre-review validator depends on this interface explicitly. A resolver
must verify the accepted registry entry and retained bytes before it can return
text extracted from a declared structural locator.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from dynamislm.benchmark.contracts import EvidenceExcerpt

SOURCE_REGISTRY_VERSION = "performance-science-eval-source-record@1.2.0"
JATS_TEXT_LOCATOR_PREFIX = "jats-text-v1:"
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_JATS_PATH_SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_.-]*)\[([1-9][0-9]*)\]\Z")


@dataclass(frozen=True, slots=True)
class SourceArtifactResolution:
    """Verified source-family identity and text derived from retained JATS bytes."""

    source_family_id: str
    source_family_digest: str
    extracted_text: str


class SourceArtifactResolver(Protocol):
    """Explicit dependency for validating source-backed candidate evidence."""

    def resolve(self, excerpt: EvidenceExcerpt) -> SourceArtifactResolution:
        """Resolve registry identity, retained bytes, locator, and extraction rule."""


def _read_json(path: Path, description: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is unavailable or invalid") from exc


def _read_jsonl(path: Path, description: str) -> tuple[dict[str, object], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"{description} is unavailable") from exc
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{description} has invalid JSON at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{description} row {line_number} must be an object")
        rows.append(row)
    return tuple(rows)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"source registry {field_name} must be an object")
    return value


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _extract_jats_text(uncompressed_jats: bytes, locator: str) -> str:
    """Apply JATS_TEXT_CONTENT_V1 to one explicitly indexed structural path.

    Locator syntax is ``jats-text-v1:/article[1]/body[1]/sec[2]/p[1]``.
    Each segment selects a one-based occurrence among direct children with the
    local tag name. The first segment must select the root. The extraction rule is
    the exact concatenation of the selected element's ``itertext()`` values;
    no whitespace normalization or document-wide text search is performed.
    """

    if not isinstance(locator, str) or not locator.startswith(JATS_TEXT_LOCATOR_PREFIX):
        raise ValueError("source locator must declare the versioned jats-text-v1 extraction rule")
    path = locator[len(JATS_TEXT_LOCATOR_PREFIX) :]
    if not path.startswith("/"):
        raise ValueError("JATS structural locator must be an absolute element path")
    raw_segments = path[1:].split("/")
    if not raw_segments or any(not segment for segment in raw_segments):
        raise ValueError("JATS structural locator contains an empty path segment")
    segments: list[tuple[str, int]] = []
    for raw_segment in raw_segments:
        match = _JATS_PATH_SEGMENT.fullmatch(raw_segment)
        if match is None:
            raise ValueError("JATS structural locator segment must use an explicit one-based index")
        segments.append((match.group(1), int(match.group(2))))

    try:
        root = ET.fromstring(uncompressed_jats)
    except ET.ParseError as exc:
        raise ValueError("retained source artifact is not valid JATS XML") from exc
    root_tag, root_index = segments[0]
    root_local_name = root.tag.rsplit("}", 1)[-1]
    if root_index != 1 or root_local_name != root_tag:
        raise ValueError("JATS structural locator does not identify the document root")
    selected = root
    for tag, occurrence in segments[1:]:
        matches = [child for child in selected if child.tag.rsplit("}", 1)[-1] == tag]
        if len(matches) < occurrence:
            raise ValueError("JATS structural locator does not resolve in retained article.xml.gz")
        selected = matches[occurrence - 1]
    return "".join(selected.itertext())


@dataclass(frozen=True, slots=True)
class PhaseASourceArtifactResolver:
    """Resolve evidence against an accepted Phase-A registry and retained store."""

    accepted_registry_path: Path
    checksum_registry_path: Path
    registry_schema_path: Path
    retained_source_root: Path

    def resolve(self, excerpt: EvidenceExcerpt) -> SourceArtifactResolution:
        if not isinstance(excerpt, EvidenceExcerpt):
            raise TypeError("excerpt must be EvidenceExcerpt")
        schema = _read_json(self.registry_schema_path, "Phase-A source registry schema")
        if not isinstance(schema, dict) or schema.get("schema_version") != SOURCE_REGISTRY_VERSION:
            raise ValueError("Phase-A source registry schema version is not the repaired authority")

        documents = _read_jsonl(self.accepted_registry_path, "Phase-A accepted source registry")
        checksums = _read_jsonl(self.checksum_registry_path, "Phase-A checksum registry")
        matching_rows_list: list[dict[str, object]] = []
        for row in documents:
            retained_artifact = row.get("retained_source_artifact")
            if (
                isinstance(retained_artifact, dict)
                and retained_artifact.get("document_identity_id")
                == excerpt.document_identity.document_id
            ):
                matching_rows_list.append(row)
        matching_rows = tuple(matching_rows_list)
        if len(matching_rows) != 1:
            raise ValueError(
                "source document identity does not resolve uniquely in Phase-A registry"
            )

        row = matching_rows[0]
        artifact = _mapping(row.get("retained_source_artifact"), "retained_source_artifact")
        version_identity = _mapping(
            row.get("pmc_article_version_identity"), "pmc_article_version_identity"
        )
        family = _mapping(row.get("source_family_identity"), "source_family_identity")
        versions = version_identity.get("pmcid_version_ids")
        if not isinstance(versions, list) or len(versions) != 1 or not isinstance(versions[0], str):
            raise ValueError("Phase-A document version identity is missing or ambiguous")
        version = versions[0]

        expected_document = (
            artifact.get("document_identity_id"),
            version,
            row.get("document_content_sha256"),
            row.get("doi"),
        )
        observed_document = (
            excerpt.document_identity.document_id,
            excerpt.document_identity.version,
            excerpt.document_identity.content_digest,
            excerpt.document_identity.doi,
        )
        if observed_document != expected_document:
            raise ValueError(
                "document identity/version/digest does not match Phase-A source registry"
            )

        expected_artifact = (
            artifact.get("source_artifact_id"),
            artifact.get("document_identity_id"),
            version,
            version,
            artifact.get("compressed_sha256"),
        )
        observed_artifact = (
            excerpt.source_artifact_identity.artifact_id,
            excerpt.source_artifact_identity.document_id,
            excerpt.source_artifact_identity.document_version,
            excerpt.source_artifact_identity.artifact_version,
            excerpt.source_artifact_identity.content_digest,
        )
        if observed_artifact != expected_artifact:
            raise ValueError("source artifact identity/digest does not match Phase-A registry")

        pmcid = row.get("pmcid")
        relative_path = artifact.get("relative_path")
        checksum_matches = tuple(
            record
            for record in checksums
            if record.get("pmcid") == pmcid and record.get("relative_path") == relative_path
        )
        if len(checksum_matches) != 1:
            raise ValueError("source artifact does not resolve uniquely in checksum registry")
        checksum = checksum_matches[0]
        identity_binding = _mapping(checksum.get("identity_binding"), "checksum.identity_binding")

        compressed_digest = artifact.get("compressed_sha256")
        document_digest = row.get("document_content_sha256")
        relative_parts = (
            PurePosixPath(relative_path).parts if isinstance(relative_path, str) else ()
        )
        if (
            row.get("disposition") != "ACCEPTED"
            or row.get("schema_version") != SOURCE_REGISTRY_VERSION
            or row.get("source_artifact_sha256") != checksum.get("sha256")
            or compressed_digest != checksum.get("sha256")
            or document_digest != checksum.get("uncompressed_jats_sha256")
            or document_digest != artifact.get("uncompressed_jats_sha256")
            or row.get("source_metadata_sha256") != checksum.get("metadata_sha256")
            or identity_binding.get("pmcid") != pmcid
            or identity_binding.get("pmcid_version_ids") != versions
            or checksum.get("artifact_role") != "RETAINED_JATS_GZIP"
            or artifact.get("compression") != "gzip"
            or artifact.get("format") != "JATS XML"
            or relative_parts[:2] != ("sources", "accepted")
            or len(relative_parts) < 4
            or ".." in relative_parts
            or "." in relative_parts
        ):
            raise ValueError("Phase-A source registry and checksum/artifact identities disagree")
        family_id = family.get("source_family_id")
        family_digest = family.get("family_digest")
        family_status = family.get("family_resolution_status")
        if (
            not isinstance(family_id, str)
            or not family_id
            or not isinstance(family_digest, str)
            or _SHA256_PATTERN.fullmatch(family_digest) is None
            or not isinstance(family_status, str)
            or family_status in {"UNRESOLVED", "AMBIGUOUS", "UNKNOWN"}
            or not isinstance(family.get("future_split_rule"), str)
            or not family.get("future_split_rule")
        ):
            raise ValueError("Phase-A source family identity is unresolved")

        try:
            source_root = self.retained_source_root.resolve(strict=True)
            artifact_path = source_root.joinpath(*relative_parts[2:]).resolve(strict=True)
        except OSError as exc:
            raise ValueError("authoritative retained source store/artifact is unavailable") from exc
        if not artifact_path.is_relative_to(source_root) or not artifact_path.is_file():
            raise ValueError("retained source artifact path escapes the accepted source store")
        try:
            compressed_bytes = artifact_path.read_bytes()
        except OSError as exc:
            raise ValueError("authoritative retained article.xml.gz is unavailable") from exc
        if (
            _SHA256_PATTERN.fullmatch(str(compressed_digest)) is None
            or _sha256(compressed_bytes) != compressed_digest
            or len(compressed_bytes) != checksum.get("byte_count")
            or len(compressed_bytes) != artifact.get("compressed_byte_count")
        ):
            raise ValueError("retained article.xml.gz bytes do not match the Phase-A SHA-256")
        try:
            uncompressed_jats = gzip.decompress(compressed_bytes)
        except (OSError, EOFError) as exc:
            raise ValueError("retained article.xml.gz cannot be decompressed") from exc
        uncompressed_digest = _sha256(uncompressed_jats)
        uncompressed_byte_count = len(uncompressed_jats)
        if (
            uncompressed_digest != document_digest
            or uncompressed_digest != checksum.get("uncompressed_jats_sha256")
            or uncompressed_byte_count != checksum.get("uncompressed_jats_byte_count")
            or uncompressed_byte_count != artifact.get("uncompressed_jats_byte_count")
        ):
            raise ValueError("decompressed JATS bytes do not match the registered document digest")

        extracted_text = _extract_jats_text(uncompressed_jats, excerpt.span_identity.locator)
        return SourceArtifactResolution(family_id, family_digest, extracted_text)


__all__ = [
    "JATS_TEXT_LOCATOR_PREFIX",
    "SOURCE_REGISTRY_VERSION",
    "PhaseASourceArtifactResolver",
    "SourceArtifactResolution",
    "SourceArtifactResolver",
]
