"""Exact-byte training admission. Trust is installed by repository governance, not applicants."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from dynamislm.serialization import canonical_bytes, canonical_hash

TRUST_PATH = "registries/training_authority.json"


class Purpose(StrEnum):
    CPT = "CPT"
    SFT = "SFT"


class SourceClass(StrEnum):
    TEXT = "SCIENTIFIC_TEXT"
    INSTRUCTION = "ORIGINAL_INSTRUCTION"
    ENGINE = "SCIENTIFIC_ENGINE_TRACE"
    EMPIRICAL = "EMPIRICAL"


class Code(StrEnum):
    ADMITTED = "ADMITTED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    INVALID = "INVALID_RECORD"
    CONTENT = "CONTENT_MISMATCH"
    PURPOSE = "PURPOSE_DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED_OR_NOT_YET_VALID"
    CONTAMINATION = "CONTAMINATION"
    DUPLICATE = "DUPLICATE_IDENTITY"
    SYNTHETIC = "SYNTHETIC_ONLY"


@dataclass(frozen=True)
class Source:
    source_id: str
    version: str
    content_sha256: str
    source_class: SourceClass


@dataclass(frozen=True)
class Request:
    source: Source
    purpose: Purpose
    transformations: tuple[str, ...]
    partition: str = "TRAIN"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _document(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value: object = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def admit_sources(
    requests: tuple[tuple[Request, bytes, bytes], ...],
    *,
    repository_root: Path,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Reverify all inputs against HEAD on every call; never trust a saved decision.

    Each tuple contains a typed request, exact content bytes, and exact grant JSON
    bytes. The committed trust store pins grants reviewed outside this boundary.
    A license string, signature supplied by an applicant, or positive flag is not authority.
    """
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluation time must be timezone aware")
    head = _git(repository_root, "rev-parse", "HEAD")
    trust_raw = subprocess.run(
        ["git", "cat-file", "blob", f"{head}:{TRUST_PATH}"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    ).stdout
    trust = _document(trust_raw)
    if set(trust) != {"schema", "grants", "revoked", "protected_digests"}:
        raise ValueError("invalid training trust registry")
    if trust["schema"] != "RES416-TRUST-1":
        raise ValueError("unknown training trust schema")
    if not all(isinstance(trust[k], list) for k in ("grants", "revoked", "protected_digests")):
        raise ValueError("invalid trust lists")
    identities = [(r.source.source_id, r.source.version) for r, _, _ in requests]
    contents = [r.source.content_sha256 for r, _, _ in requests]
    rows: list[dict[str, Any]] = []
    for request, content, grant_raw in requests:
        source = request.source
        grant_digest = "sha256:" + hashlib.sha256(grant_raw).hexdigest()
        restrictions: dict[str, Any] = {}
        synthetic = False
        code = Code.EVIDENCE_REQUIRED
        try:
            grant = _document(grant_raw)
            pins = [p for p in trust["grants"] if p["grant_sha256"] == grant_digest]
            if not pins:
                code = Code.EVIDENCE_REQUIRED
            elif len(pins) != 1:
                code = Code.INVALID
            else:
                pin = pins[0]
                # The pinned review binds rights and contamination clearance to the same bytes.
                if not all(
                    isinstance(pin[k], str) and pin[k].strip()
                    for k in (
                        "authority",
                        "rights_evidence",
                        "independent_review",
                        "contamination_review",
                    )
                ):
                    raise ValueError("missing independently reviewed authority")
                required = {
                    "schema",
                    "source",
                    "license",
                    "model_training_use",
                    "purposes",
                    "transformations",
                    "attribution",
                    "not_before",
                    "expires",
                    "synthetic",
                    "excluded_material",
                    "partition",
                    "upstream_digests",
                }
                if set(grant) != required or grant["schema"] != "RES416-GRANT-1":
                    raise ValueError("invalid grant schema")
                for key in ("purposes", "transformations", "excluded_material", "upstream_digests"):
                    if not isinstance(grant[key], list) or not all(
                        isinstance(v, str) and v.strip() for v in grant[key]
                    ):
                        raise ValueError("invalid grant list")
                if not grant["purposes"] or not set(grant["purposes"]).issubset({"CPT", "SFT"}):
                    raise ValueError("invalid purposes")
                if source.source_class not in SourceClass or request.purpose not in Purpose:
                    raise ValueError("unknown source class or purpose")
                if grant["source"] != asdict(source):
                    code = Code.CONTENT
                elif grant["model_training_use"] != "WEIGHT_TRAINING":
                    code = Code.PURPOSE
                elif grant_digest in trust["revoked"]:
                    code = Code.REVOKED
                elif not (_time(grant["not_before"]) <= evaluated_at < _time(grant["expires"])):
                    code = Code.EXPIRED
                elif request.purpose not in grant["purposes"] or not set(
                    request.transformations
                ).issubset(grant["transformations"]):
                    code = Code.PURPOSE
                elif (
                    request.partition != "TRAIN"
                    or grant["partition"] != "TRAIN"
                    or set(grant["excluded_material"])
                    != {
                        "PSE_VALIDATION",
                        "PSE_HIDDEN_FINAL",
                        "BENCHMARK_ANSWERS",
                        "UNAPPROVED_BENCHMARK",
                        "VALIDATION",
                    }
                    or any(
                        d in trust["protected_digests"]
                        for d in (source.content_sha256, *grant["upstream_digests"])
                    )
                ):
                    code = Code.CONTAMINATION
                else:
                    if not isinstance(grant["synthetic"], bool):
                        raise ValueError("synthetic marker required")
                    if not isinstance(grant["license"], str) or not grant["license"].strip():
                        raise ValueError("license required")
                    if (
                        not isinstance(grant["attribution"], str)
                        or not grant["attribution"].strip()
                    ):
                        raise ValueError("attribution requirements required")
                    synthetic = grant["synthetic"]
                    restrictions = {
                        k: grant[k]
                        for k in (
                            "license",
                            "transformations",
                            "attribution",
                            "excluded_material",
                            "partition",
                        )
                    }
                    code = Code.ADMITTED
            if (
                not re.fullmatch(r"sha256:[0-9a-f]{64}", source.content_sha256)
                or source.content_sha256 != "sha256:" + hashlib.sha256(content).hexdigest()
            ):
                code = Code.CONTENT
            if not source.source_id.strip() or not source.version.strip():
                code = Code.INVALID
            if (
                identities.count((source.source_id, source.version)) > 1
                or contents.count(source.content_sha256) > 1
            ):
                code = Code.DUPLICATE
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            code = Code.INVALID
        rows.append(
            {
                "source": asdict(source),
                "purpose": request.purpose,
                "grant_sha256": grant_digest,
                "code": code,
                "status": "AUTHORIZED"
                if code == Code.ADMITTED
                else ("EVIDENCE_REQUIRED" if code == Code.EVIDENCE_REQUIRED else "DENIED"),
                "synthetic": synthetic,
                "restrictions": restrictions,
            }
        )
    payload = {
        "schema": "RES416-ADMISSION-1",
        "repository_head": head,
        "trust_sha256": "sha256:" + hashlib.sha256(trust_raw).hexdigest(),
        "evaluated_at": evaluated_at.astimezone(UTC).isoformat(),
        "sources": sorted(rows, key=lambda r: canonical_bytes(r)),
    }
    return {**payload, "manifest_sha256": canonical_hash(payload)}


def require_admitted(manifest: dict[str, Any], *, allow_synthetic: bool = False) -> None:
    """Check a freshly recomputed admission result before handing bytes to a loader."""
    payload = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if canonical_hash(payload) != manifest.get("manifest_sha256") or not manifest["sources"]:
        raise PermissionError(Code.INVALID)
    for row in manifest["sources"]:
        if row["code"] != Code.ADMITTED or (row["synthetic"] and not allow_synthetic):
            raise PermissionError(row["code"] if row["code"] != Code.ADMITTED else Code.SYNTHETIC)


def authorize_training_bytes(
    request: Request,
    content: bytes,
    grant: bytes,
    *,
    repository_root: Path,
    evaluated_at: datetime,
) -> bytes:
    """Loader boundary: recompute authority; serialized manifests alone confer no rights."""
    manifest = admit_sources(
        ((request, content, grant),), repository_root=repository_root, evaluated_at=evaluated_at
    )
    require_admitted(manifest)
    return content
