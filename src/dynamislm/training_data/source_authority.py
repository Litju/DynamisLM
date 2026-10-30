"""RES-416: explicit distinction between empirical qualification and LM training rights.

The four locked RES-63 empirical datasets are NOT a CPT/SFT corpus. All currently
have MODEL_TRAINING_USE=NOT_AUTHORIZED_BY_RES63 in the committed dataset registry.
Do not infer an LM training grant from publication, copyright license, canonical
population qualification, or an untrusted caller-supplied flag.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, cast

from dynamislm.ingestion.registry import load_committed_dataset_registry

LOCKED_EMPIRICAL_SOURCE_IDS = (
    "unifesp-brazil-serie-a-v1",
    "mendeley-rpl-v1",
    "mendeley-turkish-super-league-instat-v1",
    "zenodo-ekstraklasa-training-adaptation",
)
EXPECTED_RES63_TRAINING_FLAG = "NOT_AUTHORIZED_BY_RES63"
TRAINING_AUDIT_SCHEMA = "DYNAMISLM-RES416-EMPIRICAL-TRAINING-USE@1.0.0"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class TrainingSourceDecision:
    """Bound source identity and negative training-use decision; no data rows."""

    source_id: str
    source_version: str
    registry_path: str
    registry_sha256: str
    registry_git_blob_oid: str
    candidate_role: str
    qualification_state: str
    license_expression: str
    noncommercial_restriction: bool
    model_training_use: str
    training_permitted: bool
    reason_codes: tuple[str, ...]


def _required_text(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid or absent source-registry {key}")
    return value


def _mapping(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"invalid or absent source-registry {key}")
    return cast(Mapping[str, object], value)


def assess_registered_empirical_source(
    document: Mapping[str, object],
    *,
    source_id: str,
    registry_path: str,
    registry_sha256: str,
    registry_git_blob_oid: str,
) -> TrainingSourceDecision:
    """Assess committed RES-63 source metadata, never an inferred training grant."""

    if source_id not in LOCKED_EMPIRICAL_SOURCE_IDS:
        raise ValueError("not a previously locked empirical source")
    if _required_text(document, "source_id") != source_id:
        raise ValueError("source identity disagrees with the committed registry path")
    if not _SHA256.fullmatch(registry_sha256) or not _GIT_OID.fullmatch(
        registry_git_blob_oid
    ):
        raise ValueError("source registry lacks a valid committed-byte identity")
    if not registry_path.startswith("registries/datasets/") or not registry_path.endswith(
        ".json"
    ):
        raise ValueError("source registry is outside the committed metadata authority")
    version = _required_text(_mapping(document, "version"), "repository_version")
    license_record = _mapping(document, "license")
    license_expression = _required_text(license_record, "spdx_expression")
    _required_text(license_record, "assertion_source_uri")
    noncommercial = license_record.get("noncommercial_restriction")
    if not isinstance(noncommercial, bool):
        raise ValueError("source license must explicitly state noncommercial restriction")
    qualification = _required_text(document, "qualification_state")
    if qualification not in {"QUALIFIED", "QUARANTINED"}:
        raise ValueError("unknown or unverified empirical source qualification")
    candidate_role = _required_text(document, "candidate_role")
    use_flag = _required_text(document, "model_training_use")

    # RES-63 is not an LM training-use grant, even for CC-BY sources.
    # If the source registry changes, a separate documented authorization
    # mechanism must be reviewed instead of changing this negative audit.
    if use_flag != EXPECTED_RES63_TRAINING_FLAG:
        raise ValueError("an empirical registry cannot grant LM weight-training rights")

    reasons = ["RES63_DOES_NOT_AUTHORIZE_LM_TRAINING"]
    if qualification == "QUARANTINED":
        reasons.append("SOURCE_POPULATION_OR_PROVENANCE_UNRESOLVED")
    if noncommercial:
        reasons.append("NONCOMMERCIAL_LICENSE_REQUIRES_INDEPENDENT_SCOPE_CHECK")
    if document.get("granularity") == "TEAM":
        reasons.append("TEAM_AGGREGATE_NOT_ATHLETE_EMPIRICAL_RECORD")

    return TrainingSourceDecision(
        source_id=source_id,
        source_version=version,
        registry_path=registry_path,
        registry_sha256=registry_sha256,
        registry_git_blob_oid=registry_git_blob_oid,
        candidate_role=candidate_role,
        qualification_state=qualification,
        license_expression=license_expression,
        noncommercial_restriction=noncommercial,
        model_training_use=use_flag,
        training_permitted=False,
        reason_codes=tuple(reasons),
    )


def assess_locked_empirical_sources(
    *, repository_root: Path
) -> tuple[TrainingSourceDecision, ...]:
    """Inspect only committed Git registries; do not load/download athlete rows."""

    results: list[TrainingSourceDecision] = []
    for source_id in LOCKED_EMPIRICAL_SOURCE_IDS:
        registered = load_committed_dataset_registry(
            source_id, repository_root=repository_root
        )
        results.append(
            assess_registered_empirical_source(
                registered.document,
                source_id=source_id,
                registry_path=registered.registry_relative_path,
                registry_sha256=registered.registry_blob_sha256,
                registry_git_blob_oid=registered.registry_git_blob_oid,
            )
        )
    return tuple(results)


def require_training_permission(decision: TrainingSourceDecision) -> None:
    """Fail closed: none of the locked RES-63 sources has independent LM rights."""

    if not isinstance(decision, TrainingSourceDecision) or not decision.training_permitted:
        raise PermissionError("source lacks independently authorized LM training use")
    # Caller-crafted positive records cannot become authority by setting one bit.
    raise PermissionError("training authorization requires a separate trusted authority gate")


def build_training_use_report(*, repository_root: Path) -> dict[str, Any]:
    """Produce a deterministic machine-readable negative allowlist from Git."""

    root = repository_root.expanduser().resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not _GIT_OID.fullmatch(revision):
        raise ValueError("missing exact repository commit")
    decisions = assess_locked_empirical_sources(repository_root=root)
    payload: dict[str, Any] = {
        "schema_version": TRAINING_AUDIT_SCHEMA,
        "repository_head": revision,
        "source_count": len(decisions),
        "training_admitted_count": 0,
        "training_authorized": False,
        "scope": "LOCKED_RES63_EMPIRICAL_SOURCES_ONLY",
        "separate_cpt_sft_corpus_authorized": False,
        "sources": [asdict(decision) for decision in decisions],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["report_sha256"] = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return payload
