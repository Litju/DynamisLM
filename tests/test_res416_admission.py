"""Synthetic grants are installed only in isolated temporary Git repositories."""

import hashlib
import json
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import pytest

from dynamislm.serialization import canonical_hash
from dynamislm.training_data import (
    LOCKED_EMPIRICAL_SOURCE_IDS,
    Code,
    Purpose,
    Request,
    Source,
    SourceClass,
    admit_sources,
    authorize_training_bytes,
    require_admitted,
)

NOW = datetime(2026, 10, 30, tzinfo=UTC)
CONTENT = b"SYNTHETIC RES416: independently authored test instruction."


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def fixture(
    root: Path,
    *,
    changes: dict[str, Any] | None = None,
    revoked: bool = False,
    protected: bool = False,
) -> tuple[Request, bytes]:
    source = Source("synthetic-res416", "1", digest(CONTENT), SourceClass.INSTRUCTION)
    grant = {
        "schema": "RES416-GRANT-1",
        "source": asdict(source),
        "license": "SYNTHETIC-TEST",
        "model_training_use": "WEIGHT_TRAINING",
        "purposes": ["SFT"],
        "transformations": ["tokenize"],
        "attribution": "Synthetic test only",
        "not_before": "2026-01-01T00:00:00+00:00",
        "expires": "2027-01-01T00:00:00+00:00",
        "synthetic": True,
        "excluded_material": [
            "PSE_VALIDATION",
            "PSE_HIDDEN_FINAL",
            "BENCHMARK_ANSWERS",
            "UNAPPROVED_BENCHMARK",
            "VALIDATION",
        ],
        "partition": "TRAIN",
        "upstream_digests": [],
    }
    grant.update(changes or {})
    raw = json.dumps(grant).encode()
    trust = {
        "schema": "RES416-TRUST-1",
        "grants": [
            {
                "grant_sha256": digest(raw),
                "authority": "SYNTHETIC authority",
                "rights_evidence": "SYNTHETIC evidence",
                "independent_review": "SYNTHETIC review",
                "contamination_review": "SYNTHETIC review",
            }
        ],
        "revoked": [digest(raw)] if revoked else [],
        "protected_digests": [digest(CONTENT)] if protected else [],
    }
    (root / "registries").mkdir(exist_ok=True)
    (root / "registries/training_authority.json").write_text(json.dumps(trust))
    for args in (
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "synthetic trust",
        ),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return Request(source, Purpose.SFT, ("tokenize",)), raw


def test_round_trip(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path)
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    assert manifest == admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    assert manifest["sources"][0]["code"] == Code.ADMITTED
    with pytest.raises(PermissionError, match="diagnostic only"):
        require_admitted(manifest, allow_synthetic=True)
    assert CONTENT.decode() not in json.dumps(manifest)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("altered", Code.CONTENT),
        ("forged", Code.EVIDENCE_REQUIRED),
        ("revoked", Code.REVOKED),
        ("expired", Code.EXPIRED),
        ("purpose", Code.PURPOSE),
        ("duplicate", Code.DUPLICATE),
        ("pse", Code.CONTAMINATION),
        ("validation", Code.CONTAMINATION),
        ("exclusions", Code.CONTAMINATION),
        ("version", Code.CONTENT),
        ("transform", Code.PURPOSE),
        ("malformed", Code.INVALID),
    ],
)
def test_rejections(tmp_path: Path, case: str, expected: Code) -> None:
    changes: dict[str, Any] = {}
    if case == "expired":
        changes["expires"] = "2026-02-01T00:00:00+00:00"
    if case == "exclusions":
        changes["excluded_material"] = []
    request, grant = fixture(
        tmp_path, changes=changes, revoked=case == "revoked", protected=case == "pse"
    )
    content = CONTENT + b"tampered" if case == "altered" else CONTENT
    if case == "forged":
        grant += b" "
    if case == "malformed":
        grant = b"not json"
    if case == "purpose":
        request = replace(request, purpose=Purpose.CPT)
    if case == "version":
        request = replace(request, source=replace(request.source, version="2"))
    if case == "validation":
        request = replace(request, partition="VALIDATION")
    if case == "transform":
        request = replace(request, transformations=("unapproved",))
    items = ((request, content, grant),) * (2 if case == "duplicate" else 1)
    manifest = admit_sources(items, repository_root=tmp_path, evaluated_at=NOW)
    assert all(row["code"] == expected for row in manifest["sources"])
    with pytest.raises(PermissionError):
        require_admitted(manifest, allow_synthetic=True)


def test_uncommitted_grants_not_authority(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path)
    (tmp_path / "registries/training_authority.json").write_text("{}")
    result = admit_sources(((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW)
    assert result["sources"][0]["code"] == Code.ADMITTED


@pytest.mark.parametrize("source_class", list(SourceClass))
@pytest.mark.parametrize("purpose", list(Purpose))
def test_supported_classes_and_purposes(
    tmp_path: Path, source_class: SourceClass, purpose: Purpose
) -> None:
    source = Source("synthetic-res416", "1", digest(CONTENT), source_class)
    request, grant = fixture(tmp_path, changes={"source": asdict(source), "purposes": [purpose]})
    request = replace(request, source=source, purpose=purpose)
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    expected = Code.QUALIFICATION if source_class == SourceClass.EMPIRICAL else Code.ADMITTED
    assert manifest["sources"][0]["code"] == expected


def test_manifest_tampering(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path)
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    manifest["sources"][0]["synthetic"] = False
    with pytest.raises(PermissionError, match="diagnostic only"):
        require_admitted(manifest)


def test_attacker_repository_cannot_release_bytes(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path, changes={"synthetic": False})
    attack: dict[str, Any] = {"repository_root": tmp_path, "evaluated_at": NOW}
    with pytest.raises(TypeError):
        authorize_training_bytes(request, CONTENT, grant, **attack)


def test_backdated_live_release_is_refused(tmp_path: Path) -> None:
    request, grant = fixture(
        tmp_path, changes={"synthetic": False, "expires": "2026-02-01T00:00:00+00:00"}
    )
    attack: dict[str, Any] = {"evaluated_at": datetime(2026, 1, 15, tzinfo=UTC)}
    with pytest.raises(TypeError):
        authorize_training_bytes(request, CONTENT, grant, **attack)


def test_rehashed_manifest_is_not_permission(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path)
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    manifest["sources"][0]["synthetic"] = False
    manifest["sources"][0]["code"] = Code.ADMITTED
    manifest["manifest_sha256"] = canonical_hash(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    )
    with pytest.raises(PermissionError):
        require_admitted(manifest)


@pytest.mark.parametrize("source_id", LOCKED_EMPIRICAL_SOURCE_IDS)
@pytest.mark.parametrize("source_class", list(SourceClass))
def test_locked_identity_cannot_be_relabelled(
    tmp_path: Path, source_class: SourceClass, source_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Source(source_id, "1", digest(CONTENT), source_class)
    request, grant = fixture(tmp_path, changes={"source": asdict(source), "synthetic": False})
    request = replace(request, source=source)
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    assert manifest["sources"][0]["code"] == Code.QUALIFICATION
    install_test_authority(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match=Code.QUALIFICATION):
        authorize_training_bytes(request, CONTENT, grant)


def install_test_authority(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-only provisioning; no caller-selectable trust or clock in the production API."""
    import dynamislm.training_data.admission as admission

    monkeypatch.setattr(admission, "_PRODUCTION_ROOT", root)
    monkeypatch.setattr(
        admission,
        "_PRODUCTION_TRUST_SHA256",
        digest((root / "registries/training_authority.json").read_bytes()),
    )

    class TestClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Self:
            return cls.fromtimestamp(NOW.timestamp(), tz=UTC)

    monkeypatch.setattr(admission, "datetime", TestClock)


def test_live_clock_rejects_expired_historical_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, grant = fixture(
        tmp_path, changes={"synthetic": False, "expires": "2026-02-01T00:00:00+00:00"}
    )
    historical = admit_sources(
        ((request, CONTENT, grant),),
        repository_root=tmp_path,
        evaluated_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    assert historical["sources"][0]["code"] == Code.ADMITTED
    install_test_authority(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match=Code.EXPIRED):
        authorize_training_bytes(request, CONTENT, grant)
    with pytest.raises(PermissionError):
        require_admitted(json.loads(json.dumps(historical)))


def test_provisioned_live_release_and_revocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, grant = fixture(tmp_path, changes={"synthetic": False})
    install_test_authority(tmp_path, monkeypatch)
    assert authorize_training_bytes(request, CONTENT, grant) == CONTENT
    with pytest.raises(PermissionError, match=Code.CONTENT):
        authorize_training_bytes(request, CONTENT + b"tampered", grant)
    fixture(tmp_path, changes={"synthetic": False}, revoked=True)
    # A new HEAD is insufficient: authority bytes must also be independently provisioned.
    with pytest.raises(PermissionError, match="unprovisioned"):
        authorize_training_bytes(request, CONTENT, grant)
    install_test_authority(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match=Code.REVOKED):
        authorize_training_bytes(request, CONTENT, grant)


def test_substituted_trust_without_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamislm.training_data.admission as admission

    request, grant = fixture(tmp_path, changes={"synthetic": False})
    monkeypatch.setattr(admission, "_PRODUCTION_ROOT", tmp_path)
    with pytest.raises(PermissionError, match="unprovisioned"):
        authorize_training_bytes(request, CONTENT, grant)


def test_audit_positive_is_not_production_authority(tmp_path: Path) -> None:
    request, grant = fixture(tmp_path, changes={"synthetic": False})
    manifest = admit_sources(
        ((request, CONTENT, grant),), repository_root=tmp_path, evaluated_at=NOW
    )
    assert manifest["sources"][0]["code"] == Code.ADMITTED
    with pytest.raises(PermissionError, match=Code.EVIDENCE_REQUIRED):
        authorize_training_bytes(request, CONTENT, grant)


def test_live_release_rejects_synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request, grant = fixture(tmp_path)
    install_test_authority(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match=Code.SYNTHETIC):
        authorize_training_bytes(request, CONTENT, grant)
