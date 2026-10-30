"""Adversarial RES-416 tests: source ingestion is not model-training authority."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm.ingestion.registry import load_committed_dataset_registry
from dynamislm.training_data.source_authority import (
    LOCKED_EMPIRICAL_SOURCE_IDS,
    assess_locked_empirical_sources,
    assess_registered_empirical_source,
    build_training_use_report,
    require_training_permission,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _source(source_id: str) -> tuple[dict[str, object], dict[str, str]]:
    registry = load_committed_dataset_registry(source_id, repository_root=_REPO_ROOT)
    return (
        copy.deepcopy(registry.document),
        {
            "source_id": source_id,
            "registry_path": registry.registry_relative_path,
            "registry_sha256": registry.registry_blob_sha256,
            "registry_git_blob_oid": registry.registry_git_blob_oid,
        },
    )


def test_all_locked_sources_are_metadata_only_and_training_denied() -> None:
    decisions = assess_locked_empirical_sources(repository_root=_REPO_ROOT)
    assert tuple(item.source_id for item in decisions) == LOCKED_EMPIRICAL_SOURCE_IDS
    assert len(decisions) == 4
    assert all(not item.training_permitted for item in decisions)
    assert all("RES63_DOES_NOT_AUTHORIZE_LM_TRAINING" in item.reason_codes for item in decisions)
    assert decisions[0].qualification_state == "QUALIFIED"
    assert decisions[0].license_expression == "CC-BY-NC-4.0"
    assert "NONCOMMERCIAL_LICENSE_REQUIRES_INDEPENDENT_SCOPE_CHECK" in decisions[0].reason_codes
    assert all(item.qualification_state == "QUARANTINED" for item in decisions[1:])
    assert "TEAM_AGGREGATE_NOT_ATHLETE_EMPIRICAL_RECORD" in decisions[2].reason_codes
    for item in decisions:
        with pytest.raises(PermissionError, match="lacks independently authorized"):
            require_training_permission(item)


def test_forged_training_authorization_flag_is_rejected() -> None:
    doc, refs = _source(LOCKED_EMPIRICAL_SOURCE_IDS[0])
    doc["model_training_use"] = "AUTHORIZED"
    with pytest.raises(ValueError, match="cannot grant LM weight-training rights"):
        assess_registered_empirical_source(doc, **refs)


def test_qualification_and_license_cannot_be_inferred_or_forged() -> None:
    doc, refs = _source(LOCKED_EMPIRICAL_SOURCE_IDS[1])
    doc["qualification_state"] = "QUALIFIED"
    result = assess_registered_empirical_source(doc, **refs)
    assert not result.training_permitted

    doc["qualification_state"] = "TRUST_ME"
    with pytest.raises(ValueError, match="unknown or unverified"):
        assess_registered_empirical_source(doc, **refs)
    doc["qualification_state"] = "QUARANTINED"

    lic = doc["license"]
    assert isinstance(lic, dict)
    lic["noncommercial_restriction"] = "false"
    with pytest.raises(ValueError, match="noncommercial restriction"):
        assess_registered_empirical_source(doc, **refs)


def test_unknown_source_and_modified_identity_fail_closed() -> None:
    doc, refs = _source(LOCKED_EMPIRICAL_SOURCE_IDS[0])
    with pytest.raises(ValueError, match="previously locked"):
        assess_registered_empirical_source(doc, **{**refs, "source_id": "new-source"})
    doc["source_id"] = LOCKED_EMPIRICAL_SOURCE_IDS[1]
    with pytest.raises(ValueError, match="identity disagrees"):
        assess_registered_empirical_source(doc, **refs)
    doc["source_id"] = LOCKED_EMPIRICAL_SOURCE_IDS[0]
    with pytest.raises(ValueError, match="committed-byte identity"):
        assess_registered_empirical_source(doc, **{**refs, "registry_sha256": "sha256:" + "0" * 63})


def test_fabricated_positive_decision_is_not_permission() -> None:
    real = assess_locked_empirical_sources(repository_root=_REPO_ROOT)[0]
    with pytest.raises(PermissionError, match="requires a separate trusted authority"):
        require_training_permission(replace(real, training_permitted=True))


def test_report_is_reproducible_binds_git_head_and_has_no_athlete_rows() -> None:
    first = build_training_use_report(repository_root=_REPO_ROOT)
    second = build_training_use_report(repository_root=_REPO_ROOT)
    assert first == second
    assert first["training_authorized"] is False
    assert first["training_admitted_count"] == 0
    assert first["source_count"] == 4
    assert len(first["repository_head"]) == 40
    serialized = json.dumps(first, sort_keys=True).lower()
    assert "athlete_id" not in serialized
    assert "canonical/unifesp" not in serialized
    assert all(
        item["registry_git_blob_oid"] and item["registry_sha256"].startswith("sha256:")
        for item in first["sources"]
    )
