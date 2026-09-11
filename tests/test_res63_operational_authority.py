from __future__ import annotations

import datetime as datetime_module
import hashlib
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from dynamislm.ingestion import (
    CanonicalEmpiricalArtifactReceipt,
    CanonicalEmpiricalRecord,
    CanonicalFootballContext,
    DatasetLicenseIdentity,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    FileRepresentation,
    PromotionDecision,
    PromotionEvidence,
    PromotionStatus,
    RawRowIdentity,
    RegisteredDatasetFileIdentity,
    RuntimeAuthorityIdentity,
    SourceVariableIdentity,
    SourceVariableRole,
    VariableResolutionStatus,
    acquire_bytes,
    build_canonical_source,
    build_raw_to_canonical_lineage,
    build_source_variable_registry,
    capture_metadata_snapshot,
    content_addressed_object_path,
    load_committed_dataset_registry,
    promotion_from_evidence,
    qualify_dataset,
    validate_canonical_records,
    verify_registered_artifact,
    write_canonical_jsonl,
    write_external_json,
)
from dynamislm.measurement import InstanceIdentifier, RegistryReference, ScientificIdentifier
from dynamislm.population.models import (
    AgeClass,
    CompetitionIdentity,
    CompetitionTier,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationIdentity,
    ProfessionalStatus,
    Sex,
    Sport,
    SquadLevel,
)
from dynamislm.serialization import canonical_json, from_canonical_json


@dataclass(frozen=True)
class PromotionFixture:
    repository_root: Path
    data_root: Path
    registry_path: Path
    source: DatasetSourceIdentity
    version: DatasetVersionIdentity
    registered: RegisteredDatasetFileIdentity
    evidence: PromotionEvidence
    metadata_snapshot_sha256: str
    canonical_relative_path: str
    variable_registry_relative_path: str
    canonical_receipt_relative_path: str


def _git(repository_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("synthetic-res63", object_type, key, "1.0.0"),
        label,
    )


def _population() -> PopulationIdentity:
    values = (
        (PopulationDimension.SEX, Sex.MALE),
        (PopulationDimension.AGE_CLASS, AgeClass.SENIOR),
        (PopulationDimension.SPORT, Sport.ASSOCIATION_FOOTBALL),
        (PopulationDimension.PROFESSIONAL_STATUS, ProfessionalStatus.PROFESSIONAL),
        (PopulationDimension.SQUAD_LEVEL, SquadLevel.FIRST_TEAM),
        (PopulationDimension.COMPETITION_TIER, CompetitionTier.TOP_DOMESTIC_DIVISION),
    )
    return PopulationIdentity(
        sex=Sex.MALE,
        age_class=AgeClass.SENIOR,
        sport=Sport.ASSOCIATION_FOOTBALL,
        professional_status=ProfessionalStatus.PROFESSIONAL,
        squad_level=SquadLevel.FIRST_TEAM,
        competition_tier=CompetitionTier.TOP_DOMESTIC_DIVISION,
        competition_identity=CompetitionIdentity(
            ScientificIdentifier("synthetic-res63", "competition", "synthetic", "1.0.0"),
            "Synthetic top domestic division",
        ),
        evidence_bindings=tuple(
            PopulationEvidenceBinding(
                dimension,
                value.value,
                _reference("population-evidence", dimension.value.lower(), dimension.value),
                source_note="deterministic synthetic operational-authority fixture",
            )
            for dimension, value in values
        ),
    )


def _source() -> DatasetSourceIdentity:
    return DatasetSourceIdentity(
        source_id="synthetic-authority-source",
        provider="Synthetic provider",
        title="Synthetic operational authority source",
        landing_page_uri="https://example.invalid/synthetic-source",
        persistent_identifier="doi:10.0000/synthetic-authority-source",
    )


def _version() -> DatasetVersionIdentity:
    return DatasetVersionIdentity(
        repository_version="1",
        version_specific_persistent_identifier="doi:10.0000/synthetic-authority-source.v1",
        published_at=datetime_module.date(2026, 1, 1),
    )


def _license() -> DatasetLicenseIdentity:
    return DatasetLicenseIdentity(
        spdx_expression="CC-BY-4.0",
        canonical_uri="https://creativecommons.org/licenses/by/4.0/",
        assertion_source_uri="https://example.invalid/synthetic-license",
        attribution_required=True,
        noncommercial_restriction=False,
    )


def _records(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    raw_sha256: str,
    population_decision: object,
    source_decision: object,
) -> tuple[CanonicalEmpiricalRecord, ...]:
    variable = SourceVariableIdentity(
        original_column_name="SyntheticMetric",
        source_label="SyntheticMetric",
        source_role=SourceVariableRole.DIRECT_REPORTED,
        source_provider=source.provider,
        source_reported_unit="arbitrary source unit",
        source_definition_reference="https://example.invalid/synthetic-definition",
    )
    records: list[CanonicalEmpiricalRecord] = []
    for row_number in (1, 2):
        canonical_id = (
            f"{source.source_id}:{version.repository_version}:{row_number}:SyntheticMetric"
        )
        records.append(
            CanonicalEmpiricalRecord(
                source_identity=source,
                version_identity=version,
                raw_row_identity=RawRowIdentity(
                    source_id=source.source_id,
                    source_version=version.repository_version,
                    raw_artifact_sha256=raw_sha256,
                    source_row_number=row_number,
                    natural_source_key=f"synthetic-{row_number}",
                    source_athlete_id=f"synthetic-athlete-{row_number}",
                ),
                football_context=CanonicalFootballContext(
                    athlete_id=InstanceIdentifier("athlete", f"synthetic-athlete-{row_number}"),
                    session_id=InstanceIdentifier("session", f"synthetic-session-{row_number}"),
                    observed_date=datetime_module.date(2026, 1, row_number),
                    position="synthetic-position",
                ),
                variable_identity=variable,
                source_reported_value=float(row_number),
                population_decision=population_decision,  # type: ignore[arg-type]
                source_decision=source_decision,  # type: ignore[arg-type]
                mapping_version="synthetic-authority-mapping@1.0.0",
                lineage=build_raw_to_canonical_lineage(
                    source_id=source.source_id,
                    source_version=version.repository_version,
                    raw_artifact_sha256=raw_sha256,
                    acquisition_receipt_id=f"acquisition:{raw_sha256}",
                    schema_sha256="sha256:" + "b" * 64,
                    source_row_number=row_number,
                    mapping_version="synthetic-authority-mapping@1.0.0",
                    canonical_record_id=canonical_id,
                ),
            )
        )
    return tuple(records)


def _fixture(tmp_path: Path) -> PromotionFixture:
    repository_root = tmp_path / "synthetic-repository"
    repository_root.mkdir()
    _git(repository_root, "init", "--quiet")
    _git(repository_root, "config", "user.email", "res63-test@example.invalid")
    _git(repository_root, "config", "user.name", "RES-63 synthetic test")
    data_root = tmp_path / "synthetic-data"

    source = _source()
    version = _version()
    license_identity = _license()
    metadata_snapshot_sha256 = capture_metadata_snapshot(
        source,
        version,
        {
            "provider": source.provider,
            "source_id": source.source_id,
            "version": version.repository_version,
            "verified_fixture": True,
        },
        data_root=data_root,
        repository_root=repository_root,
    )
    content = b"synthetic operational authority bytes\n"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    registered = RegisteredDatasetFileIdentity(
        source_id=source.source_id,
        source_version=version.repository_version,
        representation=FileRepresentation.PROVIDER_FILE,
        provider_file_id="synthetic-file-1",
        file_persistent_identifier="doi:10.0000/synthetic-file-1",
        filename="synthetic-authority.bin",
        media_type="application/octet-stream",
        expected_sha256=digest,
        expected_byte_size=len(content),
    )
    artifact = acquire_bytes(
        source,
        version,
        content,
        requested_url="https://example.invalid/synthetic-authority.bin",
        original_filename=registered.filename,
        media_type=registered.media_type,
        registered_file_identity=registered,
        representation=registered.representation,
        provider_file_id=registered.provider_file_id,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        data_root=data_root,
        repository_root=repository_root,
    )
    source_version_verification = verify_registered_artifact(
        registered,
        artifact,
        data_root=data_root,
        repository_root=repository_root,
    )

    population = _population()
    canonical_source = build_canonical_source(
        source,
        version,
        population,
        license_identity=license_identity,
        evidence_references=(_reference("source-evidence", "synthetic", "Synthetic source"),),
    )
    variable = SourceVariableIdentity(
        original_column_name="SyntheticMetric",
        source_label="SyntheticMetric",
        source_role=SourceVariableRole.DIRECT_REPORTED,
        source_provider=source.provider,
        source_reported_unit="arbitrary source unit",
        source_definition_reference="https://example.invalid/synthetic-definition",
    )
    qualification = qualify_dataset(
        source,
        version,
        population,
        canonical_source,
        artifact_sha256=artifact.sha256,
        license_identity=license_identity,
        variable_identities=(variable,),
        football_mapping_status=VariableResolutionStatus.RESOLVED,
        evidence=("https://example.invalid/synthetic-source",),
    )
    assert qualification.population_decision is not None
    assert qualification.source_decision is not None
    records = _records(
        source,
        version,
        artifact.sha256,
        qualification.population_decision,
        qualification.source_decision,
    )
    variable_registry = build_source_variable_registry(
        source.source_id,
        version.repository_version,
        "synthetic-authority-mapping@1.0.0",
        (variable,),
    )
    validation = validate_canonical_records(
        records,
        variable_registry=variable_registry,
        source_id=source.source_id,
        source_version=version.repository_version,
        raw_source_sha256=artifact.sha256,
        mapping_version=variable_registry.mapping_version,
    )
    canonical_receipt = write_canonical_jsonl(
        records,
        source_id=source.source_id,
        source_version=version.repository_version,
        raw_source_sha256=artifact.sha256,
        mapping_version=variable_registry.mapping_version,
        variable_registry=variable_registry,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        data_root=data_root,
        repository_root=repository_root,
    )
    assert canonical_receipt.canonical_artifact_sha256 == validation.canonical_artifact_sha256
    assert canonical_receipt.canonical_record_count == validation.canonical_record_count
    assert canonical_receipt.variable_registry_relative_path is not None
    canonical_receipt_relative_path = (
        "receipts/synthetic-authority-source-1-synthetic-authority-mapping-1.0.0-canonical.json"
    )
    write_external_json(
        data_root,
        "receipts/synthetic-authority-source-qualification.json",
        qualification,
    )

    registry_document = {
        "schema_version": "1.0.0",
        "source_id": source.source_id,
        "provider": source.provider,
        "title": source.title,
        "landing_page_uri": source.landing_page_uri,
        "persistent_identifier": source.persistent_identifier,
        "version": {
            "repository_version": version.repository_version,
            "version_specific_persistent_identifier": (
                version.version_specific_persistent_identifier
            ),
            "published_at": "2026-01-01",
        },
        "license": {
            "spdx_expression": license_identity.spdx_expression,
            "canonical_uri": license_identity.canonical_uri,
            "assertion_source_uri": license_identity.assertion_source_uri,
            "attribution_required": license_identity.attribution_required,
            "noncommercial_restriction": license_identity.noncommercial_restriction,
        },
        "files": [
            {
                "file_id": registered.provider_file_id,
                "file_persistent_identifier": registered.file_persistent_identifier,
                "representation": registered.representation.value,
                "filename": registered.filename,
                "media_type": registered.media_type,
                "download_url": "https://example.invalid/synthetic-authority.bin",
                "sha256": registered.expected_sha256,
                "byte_size": registered.expected_byte_size,
            }
        ],
        "metadata_snapshot_sha256": metadata_snapshot_sha256,
        "qualification_state": "QUALIFIED",
        "model_training_use": "NOT_AUTHORIZED_BY_RES63",
        "canonical_artifact": {
            "relative_path": canonical_receipt.relative_path,
            "sha256": canonical_receipt.canonical_artifact_sha256,
            "record_count": canonical_receipt.canonical_record_count,
            "mapping_version": canonical_receipt.mapping_version,
            "variable_registry_sha256": canonical_receipt.variable_registry_sha256,
            "variable_registry_relative_path": canonical_receipt.variable_registry_relative_path,
        },
    }
    registry_path = repository_root / "registries" / "datasets" / f"{source.source_id}.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(registry_document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    _git(repository_root, "add", "registries/datasets/synthetic-authority-source.json")
    _git(repository_root, "commit", "--quiet", "-m", "synthetic RES-63 registry")

    evidence = PromotionEvidence(
        qualification=qualification,
        registered_file_identity=registered,
        verified_raw_artifact=artifact,
        source_version_verification=source_version_verification,
        license_identity=license_identity,
        variable_registry=variable_registry,
        canonical_validation=validation,
        runtime_authority=RuntimeAuthorityIdentity(),
    )
    return PromotionFixture(
        repository_root=repository_root,
        data_root=data_root,
        registry_path=registry_path,
        source=source,
        version=version,
        registered=registered,
        evidence=evidence,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        canonical_relative_path=canonical_receipt.relative_path,
        variable_registry_relative_path=canonical_receipt.variable_registry_relative_path,
        canonical_receipt_relative_path=canonical_receipt_relative_path,
    )


def _identity_evidence(
    fixture: PromotionFixture,
    field: str,
) -> PromotionEvidence:
    original_content = b"synthetic operational authority bytes\n"
    fake_content = b"caller-invented bytes for identity substitution"
    if field == "expected_sha256":
        fake_content = b"X" * len(original_content)
    fake_digest = "sha256:" + hashlib.sha256(fake_content).hexdigest()
    fake_values: dict[str, object] = {
        "representation": FileRepresentation.ARCHIVAL_TAB,
        "provider_file_id": "caller-file-id",
        "file_persistent_identifier": "doi:10.0000/caller-file",
        "filename": "caller-invented.bin",
        "media_type": "application/x-caller-invented",
        "expected_sha256": fake_digest,
        "expected_byte_size": len(fake_content),
        "provider_hash": "f" * 64,
        "provider_hash_algorithm": "sha256",
        "provider_hash_representation": FileRepresentation.ARCHIVAL_TAB,
    }
    changes: dict[str, object] = {field: fake_values[field]}
    if field == "provider_hash":
        changes["provider_hash_algorithm"] = "sha256"
    if field == "expected_byte_size":
        changes["expected_sha256"] = fake_digest
    if field == "provider_hash_algorithm":
        fake_values["provider_hash"] = None
        fake_values[field] = "sha512"
    if field == "provider_hash_representation":
        fake_values["provider_hash"] = None
        fake_values["provider_hash_algorithm"] = None
    if field not in {"expected_sha256", "expected_byte_size"}:
        fake_content = b"synthetic operational authority bytes\n"
        fake_values["expected_sha256"] = fixture.registered.expected_sha256
        fake_values["expected_byte_size"] = fixture.registered.expected_byte_size
    fake = replace(fixture.registered, **changes)  # type: ignore[arg-type]
    artifact = acquire_bytes(
        fixture.source,
        fixture.version,
        fake_content,
        requested_url="https://example.invalid/synthetic-authority.bin",
        original_filename=fake.filename,
        media_type=fake.media_type,
        expected_sha256=fake.expected_sha256,
        expected_byte_size=fake.expected_byte_size,
        registered_file_identity=fake,
        representation=fake.representation,
        provider_file_id=fake.provider_file_id,
        provider_hash=fake.provider_hash,
        provider_hash_algorithm=fake.provider_hash_algorithm,
        metadata_snapshot_sha256=fixture.metadata_snapshot_sha256,
        data_root=fixture.data_root,
        repository_root=fixture.repository_root,
    )
    source_version_verification = verify_registered_artifact(
        fake,
        artifact,
        data_root=fixture.data_root,
        repository_root=fixture.repository_root,
    )
    return replace(
        fixture.evidence,
        qualification=replace(
            fixture.evidence.qualification,
            artifact_sha256=fake.expected_sha256,
        ),
        registered_file_identity=fake,
        verified_raw_artifact=artifact,
        source_version_verification=source_version_verification,
        canonical_validation=replace(
            fixture.evidence.canonical_validation,
            raw_source_sha256=fake.expected_sha256,
        ),
    )


def _promote(
    fixture: PromotionFixture,
    evidence: PromotionEvidence | None = None,
) -> PromotionDecision:
    return promotion_from_evidence(
        evidence or fixture.evidence,
        repository_root=fixture.repository_root,
        data_root=fixture.data_root,
    )


def test_committed_registry_loader_is_exact_head_authority(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    binding = load_committed_dataset_registry(
        fixture.source.source_id,
        repository_root=fixture.repository_root,
    )
    blob = fixture.registry_path.read_bytes()
    assert binding.repository_head_sha == _git(fixture.repository_root, "rev-parse", "HEAD")
    assert binding.registry_relative_path == (
        f"registries/datasets/{fixture.source.source_id}.json"
    )
    assert binding.registry_git_blob_oid == _git(
        fixture.repository_root,
        "rev-parse",
        f"HEAD:{binding.registry_relative_path}",
    )
    assert binding.registry_blob_sha256 == "sha256:" + hashlib.sha256(blob).hexdigest()
    assert binding.working_tree_matches_head


def test_operational_promotion_passes_full_synthetic_git_evidence_graph(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    decision = _promote(fixture)
    assert decision.status is PromotionStatus.PROMOTED
    assert decision.can_promote
    assert decision.evidence == fixture.evidence
    assert from_canonical_json(canonical_json(decision), PromotionDecision) == decision


def test_fallback_committed_registry_name_is_supported(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fallback = fixture.registry_path.with_name(f"{fixture.source.source_id}-v1.json")
    fallback.write_bytes(fixture.registry_path.read_bytes())
    fixture.registry_path.unlink()
    _git(fixture.repository_root, "add", "--all")
    _git(fixture.repository_root, "commit", "--quiet", "-m", "fallback registry name")
    binding = load_committed_dataset_registry(
        fixture.source.source_id,
        repository_root=fixture.repository_root,
    )
    assert binding.registry_relative_path == (
        f"registries/datasets/{fixture.source.source_id}-v1.json"
    )
    assert _promote(fixture).can_promote


@pytest.mark.parametrize(
    "field",
    (
        "representation",
        "provider_file_id",
        "file_persistent_identifier",
        "filename",
        "media_type",
        "expected_sha256",
        "expected_byte_size",
        "provider_hash",
        "provider_hash_algorithm",
        "provider_hash_representation",
    ),
)
def test_registered_identity_substitution_is_blocked_before_authorization(
    tmp_path: Path,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    forged = _identity_evidence(fixture, field)
    with pytest.raises(ValueError):
        _promote(fixture, forged)


@pytest.mark.parametrize("mutation", ("sha256", "representation"))
def test_worktree_registry_substitution_is_blocked(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    document = json.loads(fixture.registry_path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    files = document["files"]
    assert isinstance(files, list) and isinstance(files[0], dict)
    files[0][mutation] = (
        "sha256:" + "0" * 64 if mutation == "sha256" else FileRepresentation.ARCHIVAL_TAB.value
    )
    fixture.registry_path.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="WORKTREE_REGISTRY_MATCHES_HEAD"):
        _promote(fixture)


def test_untracked_only_registry_is_not_authority(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    untracked_repository = tmp_path / "untracked-only-repository"
    untracked_repository.mkdir()
    _git(untracked_repository, "init", "--quiet")
    _git(untracked_repository, "config", "user.email", "res63-test@example.invalid")
    _git(untracked_repository, "config", "user.name", "RES-63 synthetic test")
    _git(untracked_repository, "commit", "--quiet", "--allow-empty", "-m", "empty")
    untracked_path = untracked_repository / "registries" / "datasets" / fixture.registry_path.name
    untracked_path.parent.mkdir(parents=True)
    untracked_path.write_bytes(fixture.registry_path.read_bytes())
    with pytest.raises(ValueError, match="not found in HEAD"):
        promotion_from_evidence(
            fixture.evidence,
            repository_root=untracked_repository,
            data_root=fixture.data_root,
        )


def test_ambiguous_allowed_registry_paths_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fallback = fixture.registry_path.with_name(f"{fixture.source.source_id}-v1.json")
    fallback.write_bytes(fixture.registry_path.read_bytes())
    _git(
        fixture.repository_root,
        "add",
        f"registries/datasets/{fixture.source.source_id}-v1.json",
    )
    _git(fixture.repository_root, "commit", "--quiet", "-m", "ambiguous registry")
    with pytest.raises(ValueError, match="FAIL_AMBIGUOUS_REGISTRY_IDENTITY"):
        _promote(fixture)


@pytest.mark.parametrize(
    "attack",
    (
        "missing_raw",
        "corrupt_raw",
        "fabricated_acquisition",
        "wrong_acquisition_metadata",
        "missing_metadata",
        "modified_metadata",
        "mismatched_qualification",
        "mismatched_variable_registry",
        "mismatched_mapping",
        "mismatched_canonical_digest",
        "mismatched_canonical_count",
        "mismatched_canonical_receipt",
        "missing_canonical",
        "canonical_symlink_escape",
    ),
)
def test_external_attestation_and_artifact_attacks_fail_closed(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _fixture(tmp_path)
    raw_path = content_addressed_object_path(
        fixture.data_root,
        fixture.registered.expected_sha256,
    )
    if attack == "missing_raw":
        raw_path.unlink()
    elif attack == "corrupt_raw":
        raw_path.write_bytes(b"corrupted raw object")
    elif attack == "fabricated_acquisition":
        receipt = replace(
            fixture.evidence.verified_raw_artifact.acquisition_receipt,
            requested_url="https://example.invalid/fabricated",
        )
        write_external_json(
            fixture.data_root,
            "receipts/synthetic-authority-source-1-acquisition.json",
            receipt,
        )
    elif attack == "wrong_acquisition_metadata":
        receipt = replace(
            fixture.evidence.verified_raw_artifact.acquisition_receipt,
            metadata_snapshot_sha256="sha256:" + "0" * 64,
        )
        write_external_json(
            fixture.data_root,
            "receipts/synthetic-authority-source-1-acquisition.json",
            receipt,
        )
    elif attack == "missing_metadata":
        metadata_path = next((fixture.data_root / "metadata").glob("*.json"))
        metadata_path.unlink()
    elif attack == "modified_metadata":
        metadata_path = next((fixture.data_root / "metadata").glob("*.json"))
        metadata_path.write_text('{"tampered":true}\n', encoding="utf-8")
    elif attack == "mismatched_qualification":
        qualification = replace(
            fixture.evidence.qualification,
            evidence=("caller-created qualification",),
        )
        write_external_json(
            fixture.data_root,
            "receipts/synthetic-authority-source-qualification.json",
            qualification,
        )
    elif attack == "mismatched_variable_registry":
        variable_registry = replace(
            fixture.evidence.variable_registry,
            mapping_version="caller-created-mapping@1.0.0",
        )
        write_external_json(
            fixture.data_root,
            fixture.variable_registry_relative_path,
            variable_registry,
        )
    elif attack == "mismatched_mapping":
        variable_registry = replace(
            fixture.evidence.variable_registry,
            mapping_version="caller-created-mapping@1.0.0",
        )
        evidence = replace(
            fixture.evidence,
            variable_registry=variable_registry,
            canonical_validation=replace(
                fixture.evidence.canonical_validation,
                mapping_version=variable_registry.mapping_version,
                variable_registry_sha256=variable_registry.sha256,
            ),
        )
        with pytest.raises(ValueError):
            _promote(fixture, evidence)
        return
    elif attack == "mismatched_canonical_digest":
        evidence = replace(
            fixture.evidence,
            canonical_validation=replace(
                fixture.evidence.canonical_validation,
                canonical_artifact_sha256="sha256:" + "0" * 64,
            ),
        )
        with pytest.raises(ValueError):
            _promote(fixture, evidence)
        return
    elif attack == "mismatched_canonical_count":
        evidence = replace(
            fixture.evidence,
            canonical_validation=replace(
                fixture.evidence.canonical_validation,
                canonical_record_count=(
                    fixture.evidence.canonical_validation.canonical_record_count + 1
                ),
            ),
        )
        with pytest.raises(ValueError):
            _promote(fixture, evidence)
        return
    elif attack == "mismatched_canonical_receipt":
        receipt_path = fixture.data_root / fixture.canonical_receipt_relative_path
        canonical_receipt = from_canonical_json(
            receipt_path.read_text(encoding="utf-8"),
            CanonicalEmpiricalArtifactReceipt,
        )
        write_external_json(
            fixture.data_root,
            fixture.canonical_receipt_relative_path,
            replace(
                canonical_receipt,
                canonical_record_count=canonical_receipt.canonical_record_count + 1,
            ),
        )
    elif attack == "missing_canonical":
        (fixture.data_root / fixture.canonical_relative_path).unlink()
    elif attack == "canonical_symlink_escape":
        canonical_path = fixture.data_root / fixture.canonical_relative_path
        canonical_path.unlink()
        outside = tmp_path / "outside-canonical.jsonl"
        outside.write_bytes(b"outside canonical artifact")
        canonical_path.symlink_to(outside)
    else:
        raise AssertionError(f"unknown attack {attack}")
    with pytest.raises(ValueError):
        _promote(fixture)


def test_direct_decision_status_mutation_is_not_authorization(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    decision = _promote(fixture)
    with pytest.raises(ValueError, match="promotion status"):
        replace(decision, status=PromotionStatus.QUARANTINED)
    with pytest.raises(ValueError):
        replace(
            decision,
            decision_id=ScientificIdentifier("dynamislm", "promotion-decision", "forged", "1.1.0"),
        )
