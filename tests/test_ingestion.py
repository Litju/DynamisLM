from __future__ import annotations

import datetime as datetime_module
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dynamislm.ingestion import (
    CanonicalEmpiricalRecord,
    CanonicalFootballContext,
    DatasetLicenseIdentity,
    DatasetQualificationReceipt,
    DatasetQualificationStatus,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    FileRepresentation,
    PromotionEvidence,
    QuarantineReceipt,
    RawRowIdentity,
    RegisteredDatasetFileIdentity,
    RuntimeAuthorityIdentity,
    SavedOriginalVerificationReceipt,
    SourceMetadataClaim,
    SourceMetadataConflict,
    SourceVariableIdentity,
    SourceVariableRole,
    VariableResolutionStatus,
    WorkbookSchema,
    WorkbookSheetSchema,
    acquire_bytes,
    assert_external_data_root,
    build_raw_to_canonical_lineage,
    build_source_variable_registry,
    canonical_jsonl_bytes,
    canonical_replay_digest,
    inspect_tabular_schema,
    promotion_from_evidence,
    qualify_dataset,
    resolve_data_root,
    validate_canonical_records,
    validate_canonical_replay,
    verify_registered_artifact,
    verify_saved_original_url,
    write_external_json,
)
from dynamislm.ingestion.adapters.mendeley_rpl import (
    source_b_population,
    source_b_quarantine,
)
from dynamislm.ingestion.adapters.mendeley_turkish_super_league import (
    classify_source_c_granularity,
    source_c_quarantine,
)
from dynamislm.ingestion.adapters.unifesp_serie_a import (
    SOURCE_A_EXPECTED_BYTE_SIZE,
    SOURCE_A_EXPECTED_SHA256,
    SOURCE_A_ID,
    SOURCE_A_LICENSE,
    SOURCE_A_REGISTERED_FILE,
    SOURCE_A_SOURCE,
    SOURCE_A_VERSION,
    source_a_population_and_source_decisions,
    source_a_population_identity,
    source_a_representation_audit,
    source_a_season_identity,
    source_a_variable_identities,
)
from dynamislm.ingestion.storage import data_root_inventory, file_digest_and_size
from dynamislm.measurement import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MeasurementIdentity,
    MeasurementQuality,
    MeasurementResult,
    ProcessingIdentity,
    RegistryReference,
    ResultStatus,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    ScientificRole,
    SemanticIdentity,
    ValueOrigin,
    VersionIdentity,
)
from dynamislm.population.models import EvidenceClass, SeasonIdentity
from dynamislm.population.qualification import (
    qualify_canonical_population,
    qualify_canonical_source,
)
from dynamislm.provenance import ProcessingRun, Provenance, SourceArtifact
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

UTC = datetime_module.UTC
REPO_ROOT = Path(__file__).parents[1].resolve()


def _source() -> DatasetSourceIdentity:
    return DatasetSourceIdentity(
        source_id="synthetic-source",
        provider="synthetic provider",
        title="Synthetic deterministic source",
        landing_page_uri="https://example.invalid/source",
        persistent_identifier="doi:10.0000/synthetic",
    )


def _version() -> DatasetVersionIdentity:
    return DatasetVersionIdentity(
        repository_version="1",
        version_specific_persistent_identifier="doi:10.0000/synthetic.v1",
        published_at=datetime_module.date(2026, 1, 1),
    )


def _license(expression: str = "CC-BY-4.0") -> DatasetLicenseIdentity:
    return DatasetLicenseIdentity(
        spdx_expression=expression,
        canonical_uri="https://creativecommons.org/licenses/by/4.0/",
        assertion_source_uri="https://example.invalid/license",
        attribution_required=True,
        noncommercial_restriction=False,
    )


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("dynamislm", object_type, key, "1.0.0"),
        label,
    )


def _generic_identity() -> MeasurementIdentity:
    return MeasurementIdentity(
        identity_id=ScientificIdentifier("dynamislm", "measurement", "synthetic", "1.0.0"),
        semantic=SemanticIdentity(
            construct=_reference("construct", "synthetic", "Synthetic construct"),
            test_family=_reference("test-family", "synthetic", "Synthetic family"),
            protocol=None,
            measurand=_reference("measurand", "synthetic", "Synthetic measurand"),
            metric_definition=_reference("metric", "synthetic", "Synthetic metric"),
        ),
        acquisition=AcquisitionIdentity(
            device=_reference("device", "synthetic", "Synthetic device"),
            raw_artifact=InstanceIdentifier("artifact", "synthetic"),
        ),
        processing=ProcessingIdentity(),
        version=VersionIdentity(
            processing_method=_reference("processing-method", "synthetic", "Synthetic method"),
            method_registry_version="1.0.0",
            software_version="synthetic-1.0.0",
        ),
    )


def _generic_result() -> MeasurementResult:
    return MeasurementResult(
        result_id=InstanceIdentifier("result", "synthetic"),
        value=ScalarValue(1.0),
        unit=None,
        classification=ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT,
            (ScientificRole.PERFORMANCE_OUTCOME,),
        ),
        quality=MeasurementQuality(),
        status=ResultStatus.VALID,
    )


def _fixture_record(row_number: int) -> CanonicalEmpiricalRecord:
    population_decision, source_decision = source_a_population_and_source_decisions()
    source_row = RawRowIdentity(
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_artifact_sha256="sha256:" + "a" * 64,
        source_row_number=row_number,
        natural_source_key=f"{row_number}|2026-01-0{row_number}",
        source_athlete_id=f"synthetic-{row_number}",
    )
    context = CanonicalFootballContext(
        athlete_id=InstanceIdentifier("athlete", f"synthetic-{row_number}"),
        session_id=InstanceIdentifier("session", f"synthetic-session-{row_number}"),
        observed_date=datetime_module.date(2026, 1, row_number),
        competition_identity=None,
        position="synthetic-position",
    )
    variable = SourceVariableIdentity(
        original_column_name="SyntheticMetric",
        source_label="SyntheticMetric",
        source_role=SourceVariableRole.DIRECT_REPORTED,
        source_provider="synthetic provider",
        source_reported_unit="arbitrary source unit",
        source_definition_reference="https://example.invalid/definition",
    )
    canonical_id = f"{SOURCE_A_ID}:1.0:{row_number}:SyntheticMetric"
    lineage = build_raw_to_canonical_lineage(
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_artifact_sha256=source_row.raw_artifact_sha256,
        acquisition_receipt_id="acquisition:synthetic",
        schema_sha256="sha256:" + "b" * 64,
        source_row_number=row_number,
        mapping_version="synthetic-mapping@1.0.0",
        canonical_record_id=canonical_id,
    )
    return CanonicalEmpiricalRecord(
        source_identity=SOURCE_A_SOURCE,
        version_identity=SOURCE_A_VERSION,
        raw_row_identity=source_row,
        football_context=context,
        variable_identity=variable,
        source_reported_value=float(row_number),
        population_decision=population_decision,
        source_decision=source_decision,
        mapping_version="synthetic-mapping@1.0.0",
        lineage=lineage,
    )


def _promotion_evidence(tmp_path: Path) -> PromotionEvidence:
    content = b"typed promotion evidence bytes"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    registered = RegisteredDatasetFileIdentity(
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        representation=FileRepresentation.PROVIDER_FILE,
        filename="synthetic-artifact",
        media_type="application/octet-stream",
        expected_sha256=digest,
        expected_byte_size=len(content),
    )
    artifact = acquire_bytes(
        SOURCE_A_SOURCE,
        SOURCE_A_VERSION,
        content,
        original_filename=registered.filename,
        media_type=registered.media_type,
        registered_file_identity=registered,
        data_root=tmp_path / "data",
        repository_root=REPO_ROOT,
    )
    source_version_receipt = verify_registered_artifact(
        registered,
        artifact,
        data_root=tmp_path / "data",
        repository_root=REPO_ROOT,
    )
    first = _fixture_record(1)
    second = _fixture_record(2)

    def with_artifact(record: CanonicalEmpiricalRecord) -> CanonicalEmpiricalRecord:
        raw_row = replace(record.raw_row_identity, raw_artifact_sha256=digest)
        canonical_id = f"{SOURCE_A_ID}:1.0:{record.source_row_number}:SyntheticMetric"
        lineage = build_raw_to_canonical_lineage(
            source_id=SOURCE_A_ID,
            source_version=SOURCE_A_VERSION.repository_version,
            raw_artifact_sha256=digest,
            acquisition_receipt_id=f"acquisition:{digest}",
            schema_sha256="sha256:" + "b" * 64,
            source_row_number=record.source_row_number,
            mapping_version="synthetic-mapping@1.0.0",
            canonical_record_id=canonical_id,
        )
        return replace(record, raw_row_identity=raw_row, lineage=lineage)

    records = (with_artifact(first), with_artifact(second))
    variable_registry = build_source_variable_registry(
        SOURCE_A_ID,
        SOURCE_A_VERSION.repository_version,
        "synthetic-mapping@1.0.0",
        (records[0].variable_identity,),
    )
    validation = validate_canonical_records(
        records,
        variable_registry=variable_registry,
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=digest,
        mapping_version="synthetic-mapping@1.0.0",
    )
    population_decision, source_decision = source_a_population_and_source_decisions()
    qualification = DatasetQualificationReceipt(
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        status=DatasetQualificationStatus.QUALIFIED,
        population_decision=population_decision,
        source_decision=source_decision,
        artifact_sha256=digest,
        evidence_class=EvidenceClass.CANONICAL_EMPIRICAL_TARGET,
        license_identity=SOURCE_A_LICENSE,
        variable_identity_status=VariableResolutionStatus.RESOLVED,
        football_mapping_status=VariableResolutionStatus.RESOLVED,
        evidence=("synthetic typed evidence fixture",),
    )
    return PromotionEvidence(
        qualification=qualification,
        registered_file_identity=registered,
        verified_raw_artifact=artifact,
        source_version_verification=source_version_receipt,
        license_identity=SOURCE_A_LICENSE,
        variable_registry=variable_registry,
        canonical_validation=validation,
        runtime_authority=RuntimeAuthorityIdentity(),
    )


def test_data_root_containment_guard_is_symlink_aware(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    assert assert_external_data_root(external, REPO_ROOT) == external.resolve()
    with pytest.raises(ValueError):
        assert_external_data_root(REPO_ROOT / "data", REPO_ROOT)
    with pytest.raises(ValueError):
        assert_external_data_root(REPO_ROOT, REPO_ROOT)
    link = tmp_path / "external-link-to-repo"
    link.symlink_to(REPO_ROOT, target_is_directory=True)
    with pytest.raises(ValueError):
        assert_external_data_root(link, REPO_ROOT)


def test_data_root_override_and_default_are_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("DYNAMISLM_DATA_ROOT", str(override))
    assert resolve_data_root(repository_root=REPO_ROOT) == override.resolve()
    monkeypatch.delenv("DYNAMISLM_DATA_ROOT")
    assert resolve_data_root(repository_root=REPO_ROOT).is_relative_to(REPO_ROOT) is False


def test_acquisition_is_content_addressed_and_reuses_duplicate_digest(tmp_path: Path) -> None:
    content = b"synthetic deterministic bytes\n"
    digest = hashlib.sha256(content).hexdigest()
    data_root = tmp_path / "data"
    first = acquire_bytes(
        _source(),
        _version(),
        content,
        expected_sha256=digest,
        expected_byte_size=len(content),
        data_root=data_root,
        repository_root=REPO_ROOT,
    )
    second = acquire_bytes(
        _source(),
        _version(),
        content,
        expected_sha256=digest,
        expected_byte_size=len(content),
        data_root=data_root,
        repository_root=REPO_ROOT,
    )
    assert first.sha256 == second.sha256
    assert first.relative_path == second.relative_path
    assert first.relative_path == f"objects/sha256/{digest[:2]}/{digest}"
    assert data_root_inventory(data_root)["DATA_ROOT_OBJECT_COUNT"] == 1


def test_acquisition_wrong_sha_and_truncated_bytes_fail_closed(tmp_path: Path) -> None:
    content = b"complete content"
    with pytest.raises(ValueError, match="conflict"):
        acquire_bytes(
            _source(),
            _version(),
            content,
            expected_sha256="0" * 64,
            expected_byte_size=len(content),
            data_root=tmp_path / "wrong-sha",
            repository_root=REPO_ROOT,
        )
    full_digest = hashlib.sha256(content).hexdigest()
    with pytest.raises(ValueError, match="conflict"):
        acquire_bytes(
            _source(),
            _version(),
            content[:-1],
            expected_sha256=full_digest,
            expected_byte_size=len(content),
            data_root=tmp_path / "truncated",
            repository_root=REPO_ROOT,
        )


def test_license_and_metadata_conflict_contracts_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported license"):
        _license("MIT")
    with pytest.raises(ValueError, match="restriction flags"):
        DatasetLicenseIdentity(
            "CC-BY-NC-4.0",
            "https://creativecommons.org/licenses/by-nc/4.0/",
            "https://example.invalid/license",
            True,
            False,
        )
    first = SourceMetadataClaim("source", "rows", 1, "https://example.invalid/a")
    second = SourceMetadataClaim("source", "rows", 2, "https://example.invalid/b")
    conflict = SourceMetadataConflict("source", "1", "rows", (first, second), 3)
    assert conflict.verified_file_fact == 3
    with pytest.raises(ValueError, match="canonical URI"):
        DatasetLicenseIdentity(
            "CC-BY-4.0",
            "https://creativecommons.org/licenses/by-nc/4.0/",
            "https://example.invalid/license",
            True,
            False,
        )
    with pytest.raises(ValueError, match="canonical URI"):
        DatasetLicenseIdentity(
            "CC-BY-NC-4.0",
            "https://creativecommons.org/licenses/by/4.0/",
            "https://example.invalid/license",
            True,
            True,
        )


def test_representation_identity_and_path_integrity_fail_closed() -> None:
    with pytest.raises(ValueError):
        from dynamislm.ingestion.contracts import CanonicalEmpiricalArtifactReceipt

        CanonicalEmpiricalArtifactReceipt(
            source_id="source",
            source_version="1",
            raw_source_sha256="sha256:" + "a" * 64,
            canonical_artifact_sha256="sha256:" + "b" * 64,
            canonical_record_count=1,
            mapping_version="mapping@1.0.0",
            relative_path="canonical/../objects/x",
        )
    assert SOURCE_A_REGISTERED_FILE.representation is FileRepresentation.ARCHIVAL_TAB
    assert (
        SOURCE_A_REGISTERED_FILE.provider_hash_representation is FileRepresentation.SAVED_ORIGINAL
    )


def test_source_a_season_mapping_is_explicit_and_fail_closed() -> None:
    assert source_a_season_identity(datetime_module.date(2020, 1, 1)).display_label == (
        "Brazilian Serie A 2020"
    )
    assert source_a_season_identity(datetime_module.date(2024, 12, 31)).identifier.key == (
        "brazil-serie-a-2024"
    )
    with pytest.raises(ValueError, match="outside"):
        source_a_season_identity(datetime_module.date(2019, 12, 31))


def test_source_a_threshold_and_provider_identities_are_not_collapsed() -> None:
    identities = {
        item.original_column_name: item
        for item in source_a_variable_identities(
            (
                "Distance>20,0km/h(m)",
                "Distance>25,0km/h(m)",
                "Playerload",
            )
        )
    }
    assert (
        identities["Distance>20,0km/h(m)"].source_threshold_or_band
        != identities["Distance>25,0km/h(m)"].source_threshold_or_band
    )
    assert identities["Playerload"].source_role is SourceVariableRole.PROVIDER_DERIVED
    assert identities["Playerload"].source_device_or_sampling_note is not None


def test_generic_leaf_direct_runtime_attacks_fail_closed() -> None:
    identity = _generic_identity()
    result = _generic_result()
    with pytest.raises(ValueError):
        SemanticIdentity(
            "bad",  # type: ignore[arg-type]
            identity.semantic.test_family,
            None,
            identity.semantic.measurand,
            identity.semantic.metric_definition,
        )
    with pytest.raises(ValueError):
        replace(identity, semantic="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(identity, acquisition="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(result, value=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(result, classification="bad")  # type: ignore[arg-type]

    from dynamislm.measurement import ObservationContext

    with pytest.raises(ValueError):
        ObservationContext(
            context_id=InstanceIdentifier("context", "runtime-invalid"),
            athlete_id="athlete",  # type: ignore[arg-type]
            session_id=InstanceIdentifier("session", "session"),
            test_instance_id=InstanceIdentifier("test-instance", "test"),
            trial_id=None,
            observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
            population_context="synthetic",
        )
    valid_context = ObservationContext(
        context_id=InstanceIdentifier("context", "runtime"),
        athlete_id=InstanceIdentifier("athlete", "athlete"),
        session_id=InstanceIdentifier("session", "session"),
        test_instance_id=InstanceIdentifier("test-instance", "test"),
        trial_id=None,
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        population_context="synthetic",
    )
    observation = ScientificMeasurementObservation(
        InstanceIdentifier("observation", "runtime"),
        valid_context,
        identity,
        result,
        Provenance(
            provenance_id=InstanceIdentifier("provenance", "runtime"),
            source_artifacts=(),
            acquisitions=(),
            processing_runs=(),
            lineage_edges=(),
        ),
    )
    with pytest.raises(ValueError):
        replace(observation, context="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SourceArtifact("bad", "sha256:" + "a" * 64, "text/plain")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ProcessingRun(
            InstanceIdentifier("processing-run", "runtime"),
            ("bad",),  # type: ignore[arg-type]
            _reference("processing-method", "runtime", "Runtime method"),
            (),
            "runtime",
            InstanceIdentifier("observation", "runtime"),
        )
    with pytest.raises(ValueError):
        Provenance(
            InstanceIdentifier("provenance", "runtime-source"),
            ("bad",),  # type: ignore[arg-type]
            (),
            (),
            (),
        )
    with pytest.raises(ValueError):
        Provenance(
            InstanceIdentifier("provenance", "runtime-run"),
            (),
            (),
            ("bad",),  # type: ignore[arg-type]
            (),
        )


def test_direct_construction_v3_roundtrip_and_tamper_are_parity_safe() -> None:
    identity = _generic_identity()
    result = _generic_result()
    serialized = canonical_json(result)
    assert from_canonical_json(serialized, MeasurementResult) == result
    envelope = serialized.replace('"status":"VALID"', '"status":"NOT_A_STATUS"')
    with pytest.raises(ValueError):
        from_canonical_json(envelope, MeasurementResult)
    assert canonical_hash(from_canonical_json(serialized, MeasurementResult)) == canonical_hash(
        result
    )
    assert canonical_hash(identity) == canonical_hash(
        from_canonical_json(canonical_json(identity), MeasurementIdentity)
    )


def test_typed_promotion_authority_cannot_be_forged(tmp_path: Path) -> None:
    import dynamislm.ingestion as ingestion
    from dynamislm.ingestion.contracts import promotion_gate_results

    assert not hasattr(ingestion, "decide_promotion")
    evidence = _promotion_evidence(tmp_path)
    with pytest.raises(ValueError, match="REGISTERED_IDENTITY_SUBSTITUTION"):
        promotion_from_evidence(
            evidence,
            repository_root=REPO_ROOT,
            data_root=tmp_path / "data",
        )
    assert all(value for _, value in promotion_gate_results(evidence))

    unresolved = replace(
        evidence.qualification,
        status=DatasetQualificationStatus.QUARANTINED,
        evidence_class=EvidenceClass.REJECTED_OR_UNRESOLVED,
        reason_codes=("FOOTBALL_CONTEXT_UNRESOLVED",),
        missing_information=("football context evidence",),
    )
    unresolved_evidence = replace(evidence, qualification=unresolved)
    assert not dict(promotion_gate_results(unresolved_evidence))["SOURCE_QUALIFIED"]


def test_canonical_replay_is_independent_of_input_order_and_keeps_lineage() -> None:
    first = _fixture_record(1)
    second = _fixture_record(2)
    forward = canonical_jsonl_bytes((first, second))
    reverse = canonical_jsonl_bytes((second, first))
    assert forward == reverse
    assert canonical_replay_digest((first, second)) == canonical_replay_digest((first, second))
    with pytest.raises(ValueError, match="monotonic"):
        canonical_replay_digest((second, first))
    validate_canonical_replay((first, second), (first, second))
    assert b"Dateofbirth" not in forward
    assert all(
        item.startswith(prefix)
        for item, prefix in zip(
            first.lineage,
            (
                "dataset-source:",
                "dataset-version:",
                "verified-raw-artifact:",
                "acquisition-receipt:",
                "source-schema:",
                "source-row:",
                "mapping-version:",
                "canonical-record:",
            ),
            strict=True,
        )
    )


def test_lineage_identity_and_cross_athlete_attacks_fail_closed() -> None:
    record = _fixture_record(1)
    bad_artifact_lineage = (
        *record.lineage[:2],
        "verified-raw-artifact:sha256:" + "e" * 64,
        *record.lineage[3:],
    )
    with pytest.raises(ValueError):
        replace(record, lineage=bad_artifact_lineage)
    bad_row_lineage = (*record.lineage[:5], "source-row:2", *record.lineage[6:])
    with pytest.raises(ValueError):
        replace(record, lineage=bad_row_lineage)
    bad_mapping = (*record.lineage[:6], "mapping-version:other@2.0.0", *record.lineage[7:])
    with pytest.raises(ValueError):
        replace(record, lineage=bad_mapping)
    with pytest.raises(ValueError):
        replace(record, lineage=record.lineage[:-1])
    with pytest.raises(ValueError):
        replace(
            record,
            football_context=replace(
                record.football_context,
                athlete_id=InstanceIdentifier("athlete", "different-athlete"),
            ),
        )


def test_source_a_qualification_and_source_b_quarantine_reuse_existing_authority() -> None:
    population, source = source_a_population_and_source_decisions()
    assert population.passed
    assert source.passed
    b_population = source_b_population()
    assert not b_population.sex.value == "MALE"
    b_quarantine = source_b_quarantine()
    assert "UNRESOLVED_SEX_EVIDENCE" in b_quarantine.reason_codes


def test_source_c_team_aggregate_is_not_an_athlete_record() -> None:
    schema = WorkbookSchema(
        source_id="mendeley-turkish-super-league-instat-v1",
        source_version="1",
        raw_artifact_sha256="sha256:" + "c" * 64,
        sheets=(
            WorkbookSheetSchema(
                sheet_name="data",
                headers=("Tak\u0131m", "Ma\u00e7lar", "Toplam Mesafe"),
                used_range="A1:C3",
                row_count=2,
                column_count=3,
                missing_counts=(),
                structural_observed_types=(),
                distinct_athlete_ids=0,
                distinct_match_or_date_ids=2,
            ),
        ),
        schema_sha256="sha256:" + "d" * 64,
    )
    assert classify_source_c_granularity(schema) == "TEAM"
    receipt = source_c_quarantine(schema)
    assert isinstance(receipt, QuarantineReceipt)
    assert "TEAM_AGGREGATE_NOT_CANONICAL_ATHLETE_RECORD" in receipt.reason_codes
    assert "UNRESOLVED_RECORD_GRANULARITY" not in receipt.reason_codes


def test_source_a_population_requires_dimension_specific_evidence() -> None:
    population = source_a_population_identity()
    assert len(population.evidence_bindings) == 6
    assert (
        len(
            {
                binding.evidence_reference.identifier.key
                for binding in population.evidence_bindings
                if binding.evidence_reference
            }
        )
        == 6
    )
    assert not hasattr(
        __import__("dynamislm.ingestion", fromlist=["canonical_population_identity"]),
        "canonical_population_identity",
    )


def test_registered_live_provider_observation_cannot_redefine_expected_bytes() -> None:
    from dynamislm.ingestion.registry import (
        load_dataset_registry,
        registered_dataset_file_identity,
        verify_live_provider_file_observation,
    )

    registered = registered_dataset_file_identity(load_dataset_registry("mendeley-rpl-v1"))
    with pytest.raises(ValueError, match="SOURCE_VERSION_CONFLICT"):
        verify_live_provider_file_observation(
            registered,
            provider_sha256="sha256:" + "0" * 64,
            provider_hash="0" * 64,
            provider_hash_algorithm="sha256",
            provider_byte_size=registered.expected_byte_size,
            provider_file_id=registered.provider_file_id,
        )
    with pytest.raises(ValueError, match="SOURCE_VERSION_CONFLICT"):
        verify_live_provider_file_observation(
            registered,
            provider_sha256=registered.expected_sha256,
            provider_hash=registered.provider_hash,
            provider_hash_algorithm="sha256",
            provider_byte_size=registered.expected_byte_size + 1,
            provider_file_id=registered.provider_file_id,
        )


def test_streamed_writer_compacts_variable_identity_and_rejects_bad_order(tmp_path: Path) -> None:
    from dynamislm.ingestion import write_canonical_jsonl

    first = _fixture_record(1)
    second = _fixture_record(2)
    registry = build_source_variable_registry(
        SOURCE_A_ID,
        SOURCE_A_VERSION.repository_version,
        "synthetic-mapping@1.0.0",
        (first.variable_identity,),
    )
    receipt = write_canonical_jsonl(
        (first, second),
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        raw_source_sha256=first.raw_artifact_sha256,
        mapping_version="synthetic-mapping@1.0.0",
        variable_registry=registry,
        data_root=tmp_path / "data",
        repository_root=REPO_ROOT,
    )
    artifact = (tmp_path / "data" / receipt.relative_path).read_bytes()
    assert b"source_variable_id" in artifact
    assert b'"variable_identity"' not in artifact
    assert receipt.variable_registry_sha256 == registry.sha256
    with pytest.raises(ValueError, match="monotonic"):
        write_canonical_jsonl(
            (second, first),
            source_id=SOURCE_A_ID,
            source_version=SOURCE_A_VERSION.repository_version,
            raw_source_sha256=first.raw_artifact_sha256,
            mapping_version="synthetic-mapping@1.0.0",
            variable_registry=registry,
            data_root=tmp_path / "other-data",
            repository_root=REPO_ROOT,
        )


def test_tab_schema_inspection_preserves_header_and_counts() -> None:
    path = REPO_ROOT / "tests/fixtures/synthetic/source-a/source-a.tab"
    digest, size = file_digest_and_size(path)
    schema = inspect_tabular_schema(
        path,
        source_id="synthetic-source",
        source_version="1",
        raw_artifact_sha256=digest,
        original_filename="source-a.tab",
    )
    assert schema.original_filename == "source-a.tab"
    assert schema.columns == ("AthleteID", "Gamedate", "TotalDistance(m)")
    assert schema.row_count == 2
    assert schema.column_count == 3
    assert schema.distinct_athlete_ids == 2
    assert schema.distinct_game_dates == 2
    assert size > 0


def test_qualified_receipt_requires_football_mapping_and_self_consistent_decisions(
    tmp_path: Path,
) -> None:
    evidence = _promotion_evidence(tmp_path)
    with pytest.raises(ValueError, match="resolved football mapping"):
        replace(
            evidence.qualification,
            football_mapping_status=VariableResolutionStatus.UNRESOLVED,
        )

    source_decision = evidence.qualification.source_decision
    assert source_decision is not None
    with pytest.raises(ValueError, match="bound to another source"):
        replace(
            evidence.qualification,
            source_decision=qualify_canonical_source(
                replace(
                    source_decision.source,
                    source_id=RegistryReference(
                        ScientificIdentifier(
                            "dynamislm",
                            "dataset",
                            "another-source",
                            "1.0.0",
                        ),
                        "Another source",
                    ),
                )
            ),
        )

    with pytest.raises(ValueError, match="bound to another version"):
        replace(
            evidence.qualification,
            source_decision=qualify_canonical_source(
                replace(source_decision.source, source_revision="another-version")
            ),
        )

    changed_population = replace(
        evidence.qualification.population_decision.population
        if evidence.qualification.population_decision is not None
        else source_decision.population_decision.population,
        season=SeasonIdentity(
            ScientificIdentifier("dynamislm", "season", "synthetic-season", "1.0.0"),
            "Synthetic season",
        ),
    )
    changed_population_decision = qualify_canonical_population(changed_population)
    with pytest.raises(ValueError, match="decisions differ"):
        replace(evidence.qualification, population_decision=changed_population_decision)


def test_promotion_evidence_rejects_cross_bound_artifact_and_mapping(tmp_path: Path) -> None:
    evidence = _promotion_evidence(tmp_path)
    with pytest.raises(ValueError, match="qualification artifact"):
        replace(
            evidence,
            qualification=replace(
                evidence.qualification,
                artifact_sha256="sha256:" + "c" * 64,
            ),
        )
    with pytest.raises(ValueError, match="mapping"):
        replace(
            evidence,
            canonical_validation=replace(
                evidence.canonical_validation,
                mapping_version="other-mapping@1.0.0",
            ),
        )


def test_qualify_dataset_rejects_cross_bound_source_population_version_and_license() -> None:
    population_decision, source_decision = source_a_population_and_source_decisions()
    identities = source_a_variable_identities(("AthleteID",))
    common: dict[str, Any] = {
        "artifact_sha256": "sha256:" + "a" * 64,
        "license_identity": SOURCE_A_LICENSE,
        "variable_identities": identities,
        "football_mapping_status": VariableResolutionStatus.RESOLVED,
        "evidence": ("synthetic qualification evidence",),
    }
    changed_population = replace(
        population_decision.population,
        season=SeasonIdentity(
            ScientificIdentifier("dynamislm", "season", "qualification-test", "1.0.0"),
            "Qualification test season",
        ),
    )
    with pytest.raises(ValueError, match="population"):
        qualify_dataset(
            SOURCE_A_SOURCE,
            SOURCE_A_VERSION,
            changed_population,
            replace(source_decision.source, population=population_decision.population),
            **common,
        )
    with pytest.raises(ValueError, match="source"):
        qualify_dataset(
            SOURCE_A_SOURCE,
            SOURCE_A_VERSION,
            population_decision.population,
            replace(
                source_decision.source,
                source_id=RegistryReference(
                    ScientificIdentifier("dynamislm", "dataset", "other", "1.0.0"),
                    "Other",
                ),
            ),
            **common,
        )
    with pytest.raises(ValueError, match="revision"):
        qualify_dataset(
            SOURCE_A_SOURCE,
            SOURCE_A_VERSION,
            population_decision.population,
            replace(source_decision.source, source_revision="2.0"),
            **common,
        )
    with pytest.raises(ValueError, match="license"):
        qualify_dataset(
            SOURCE_A_SOURCE,
            SOURCE_A_VERSION,
            population_decision.population,
            source_decision.source,
            **{
                **common,
                "license_identity": _license("CC-BY-4.0"),
            },
        )


def test_representation_audit_uses_persisted_saved_original_observations() -> None:
    verification = SavedOriginalVerificationReceipt(
        source_id=SOURCE_A_ID,
        source_version=SOURCE_A_VERSION.repository_version,
        provider_file_id=1513,
        file_persistent_identifier="hdl:20.500.12682/rdp/GMXME8/DO2C67",
        representation=FileRepresentation.SAVED_ORIGINAL,
        provider_hash="93951f1b28240cfaa9c31d075824cb36",
        provider_hash_algorithm="md5",
        observed_md5="93951f1b28240cfaa9c31d075824cb36",
        observed_sha256="sha256:" + "a" * 64,
        observed_byte_size=1124197,
        metadata_snapshot_sha256="sha256:360e006156b81f0a25c4a5c25f350ce6f46f9084028d1938f35e998d45d3f856",
    )
    audit = source_a_representation_audit(
        verified_archival_sha256=SOURCE_A_EXPECTED_SHA256,
        verified_archival_byte_size=SOURCE_A_EXPECTED_BYTE_SIZE,
        saved_original_verification=verification,
    )
    assert audit["provider_hash_verified"] is True
    mismatched = replace(verification, metadata_snapshot_sha256="sha256:" + "b" * 64)
    assert (
        source_a_representation_audit(
            verified_archival_sha256=SOURCE_A_EXPECTED_SHA256,
            verified_archival_byte_size=SOURCE_A_EXPECTED_BYTE_SIZE,
            saved_original_verification=mismatched,
        )["provider_hash_verified"]
        is False
    )


def test_empty_included_variables_and_forged_promotion_cannot_promote(tmp_path: Path) -> None:
    from dynamislm.ingestion.contracts import promotion_gate_results

    evidence = _promotion_evidence(tmp_path)
    empty_variables = replace(
        evidence,
        canonical_validation=replace(
            evidence.canonical_validation,
            included_variable_ids=(),
        ),
    )
    gates = dict(promotion_gate_results(empty_variables))
    assert not gates["VARIABLE_IDENTITY_RESOLVED"]


def test_saved_original_verification_is_streamed_and_has_no_success_boolean(
    tmp_path: Path,
) -> None:
    source = _source()
    version = _version()
    archival = b"archival bytes"
    saved_original = b"saved-original bytes"
    registered = RegisteredDatasetFileIdentity(
        source_id=source.source_id,
        source_version=version.repository_version,
        representation=FileRepresentation.ARCHIVAL_TAB,
        filename="archival.tab",
        media_type="text/tab-separated-values",
        expected_sha256="sha256:" + hashlib.sha256(archival).hexdigest(),
        expected_byte_size=len(archival),
        provider_file_id="file-1",
        file_persistent_identifier="pid:1",
        provider_hash=hashlib.md5(saved_original).hexdigest(),
        provider_hash_algorithm="md5",
        provider_hash_representation=FileRepresentation.SAVED_ORIGINAL,
    )

    class Response:
        def __init__(self) -> None:
            self._chunks = iter((saved_original[:5], saved_original[5:]))

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://example.invalid/datafile/file-1?format=original"

        def read(self, size: int) -> bytes:
            del size
            return next(self._chunks, b"")

    receipt = verify_saved_original_url(
        source,
        version,
        "https://example.invalid/datafile/file-1?format=original",
        registered_file_identity=registered,
        file_persistent_identifier="pid:1",
        provider_file_id="file-1",
        expected_byte_size=len(saved_original),
        metadata_snapshot_sha256="sha256:" + "d" * 64,
        data_root=tmp_path / "data",
        repository_root=REPO_ROOT,
        opener=lambda request, timeout: Response(),
    )
    assert receipt.observed_md5 == hashlib.md5(saved_original).hexdigest()
    assert receipt.observed_sha256 == "sha256:" + hashlib.sha256(saved_original).hexdigest()
    assert receipt.observed_byte_size == len(saved_original)
    assert "verified" not in canonical_json(receipt)
    assert from_canonical_json(canonical_json(receipt), SavedOriginalVerificationReceipt) == receipt
    assert data_root_inventory(tmp_path / "data")["DATA_ROOT_OBJECT_COUNT"] == 0


@pytest.mark.parametrize("descendant", ("objects", "tmp/acquisition"))
@pytest.mark.parametrize("outside_target", ("repository", "directory"))
def test_nested_data_root_symlink_escape_is_blocked_before_acquisition_bytes(
    tmp_path: Path,
    descendant: str,
    outside_target: str,
) -> None:
    data_root = tmp_path / f"data-{descendant.replace('/', '-')}-{outside_target}"
    data_root.mkdir()
    outside = REPO_ROOT if outside_target == "repository" else tmp_path / "outside-directory"
    if outside_target == "directory":
        outside.mkdir()
    link = data_root / descendant
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        acquire_bytes(
            _source(),
            _version(),
            b"must not escape",
            data_root=data_root,
            repository_root=REPO_ROOT,
        )
    if outside_target == "directory":
        assert tuple(outside.iterdir()) == ()


def test_digest_target_symlink_escape_is_blocked_before_move(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    content = b"content addressed bytes"
    digest = hashlib.sha256(content).hexdigest()
    object_parent = data_root / "objects" / "sha256" / digest[:2]
    object_parent.mkdir(parents=True)
    outside_target = tmp_path / "outside-object"
    outside_target.write_bytes(b"untouched")
    target = object_parent / digest
    target.symlink_to(outside_target)
    with pytest.raises(ValueError, match="escapes"):
        acquire_bytes(
            _source(),
            _version(),
            content,
            expected_sha256=digest,
            expected_byte_size=len(content),
            data_root=data_root,
            repository_root=REPO_ROOT,
        )
    assert outside_target.read_bytes() == b"untouched"
    assert target.is_symlink()


@pytest.mark.parametrize("descendant", ("metadata", "receipts", "canonical", "quarantine"))
def test_nested_data_root_symlink_escape_is_blocked_for_json_writes(
    tmp_path: Path,
    descendant: str,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / descendant).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        write_external_json(data_root, f"{descendant}/receipt.json", {"value": "blocked"})
    assert not (outside / "receipt.json").exists()
