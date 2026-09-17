"""Source/provider qualification boundary for drop-jump observations."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass

from dynamislm.measurement.drop_jump.identity import (
    DropJumpAcquisitionIdentity,
    DropJumpAcquisitionRecord,
    DropJumpArtifactStatus,
    DropJumpMeasurementIdentity,
    DropJumpProcessingIdentity,
    DropJumpProcessingState,
    DropJumpQualificationStatus,
    DropJumpSemanticIdentity,
    DropJumpSourceArtifact,
)
from dynamislm.measurement.drop_jump.registry import (
    DROP_JUMP_QUALIFICATION_MEASURAND,
    DROP_JUMP_QUALIFICATION_METRIC,
    DROP_JUMP_REGISTRY_VERSION,
    DROP_JUMP_SOFTWARE_VERSION,
    DROP_JUMP_SOURCE_OBSERVATION_OPERATION,
    DROP_JUMP_SOURCE_QUALIFICATION_OPERATION,
    DROP_JUMP_TEST_FAMILY,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    VersionIdentity,
    _require_enum,
    _require_instance,
    _require_tuple_items,
)
from dynamislm.measurement.observation import (
    ObservationContext,
    ScientificMeasurementObservation,
    create_derived_observation,
)
from dynamislm.measurement.result import (
    CategoricalValue,
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import EvidenceReference, ProcessingRun
from dynamislm.serialization import canonical_json, register_serializable_type


def _source_processing_state(origin: ValueOrigin) -> DropJumpProcessingState:
    if origin is ValueOrigin.SOURCE_REPORTED:
        return DropJumpProcessingState.RAW_ACQUIRED
    if origin is ValueOrigin.PROVIDER_DERIVED:
        return DropJumpProcessingState.PROVIDER_PROCESSED
    raise ValueError("drop-jump source origin must be SOURCE_REPORTED or PROVIDER_DERIVED")


def _require_verified_artifact(artifact: DropJumpSourceArtifact) -> None:
    if not isinstance(artifact, DropJumpSourceArtifact):
        raise ValueError("drop-jump source artifact must use its typed artifact contract")
    if not artifact.immutable or artifact.status is not DropJumpArtifactStatus.VERIFIED:
        raise ValueError("drop-jump source artifact must be immutable and verified")


def _validate_acquisition_binding(
    identity: DropJumpMeasurementIdentity,
    artifact: DropJumpSourceArtifact,
    acquisition: DropJumpAcquisitionRecord,
) -> None:
    if not isinstance(identity.acquisition, DropJumpAcquisitionIdentity):
        raise ValueError("drop-jump identity requires typed acquisition identity")
    if identity.acquisition.raw_artifact != artifact.artifact_id:
        raise ValueError("drop-jump identity raw artifact does not match source artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("drop-jump identity acquisition does not match acquisition record")
    if acquisition.source_artifact_id != artifact.artifact_id:
        raise ValueError("drop-jump acquisition does not reference source artifact")
    expected = identity.acquisition
    if (
        expected.device != acquisition.device
        or expected.sensor_channel != acquisition.sensor_channel
        or expected.sampling != acquisition.sampling
        or expected.calibration_reference != acquisition.calibration_reference
        or expected.hardware_firmware != acquisition.hardware_firmware
        or expected.provider != acquisition.provider
        or expected.sensor_modality != acquisition.sensor_modality
        or expected.timebase != acquisition.timebase
        or expected.axis_or_frame != acquisition.axis_or_frame
    ):
        raise ValueError(
            "drop-jump identity and acquisition record do not describe the same system"
        )


def build_drop_jump_source_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: DropJumpMeasurementIdentity,
    result: MeasurementResult,
    source_artifact: DropJumpSourceArtifact,
    acquisition: DropJumpAcquisitionRecord,
    processing_run: ProcessingRun | None = None,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Create a verified DJ source/provider observation with immutable lineage."""

    _require_verified_artifact(source_artifact)
    _require_instance(context, ObservationContext, "context")
    _require_instance(identity, DropJumpMeasurementIdentity, "identity")
    _require_instance(result, MeasurementResult, "result")
    _require_instance(acquisition, DropJumpAcquisitionRecord, "acquisition")
    if observation_id.instance_type != "observation":
        raise ValueError("observation_id must identify an observation")
    _validate_acquisition_binding(identity, source_artifact, acquisition)
    origin = result.classification.value_origin
    expected_state = _source_processing_state(origin)
    if identity.processing.processing_state is not expected_state:
        raise ValueError("DJ source processing state does not match result value origin")
    if identity.processing.registered_operation not in {
        DROP_JUMP_SOURCE_OBSERVATION_OPERATION,
        DROP_JUMP_SOURCE_QUALIFICATION_OPERATION,
    }:
        raise ValueError("DJ source identity must use the registered source operation")
    if processing_run is None:
        processing_run = ProcessingRun(
            processing_run_id=InstanceIdentifier(
                "processing-run", f"drop-jump-source:{observation_id.value}"
            ),
            source_artifact_ids=(source_artifact.artifact_id,),
            method=identity.version.processing_method,
            parameters=identity.processing.method_parameters,
            software_version=identity.version.software_version,
            output_entity_id=observation_id,
        )
    if processing_run.output_entity_id != observation_id:
        raise ValueError("DJ source processing output must match observation ID")
    if processing_run.method != identity.version.processing_method:
        raise ValueError("DJ source processing method does not match identity")
    if processing_run.parameters != identity.processing.method_parameters:
        raise ValueError("DJ source processing parameters do not match identity")
    if processing_run.software_version != identity.version.software_version:
        raise ValueError("DJ source software version does not match identity")
    if source_artifact.artifact_id not in processing_run.source_artifact_ids:
        raise ValueError("DJ source processing must reference source artifact")
    return create_derived_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        processing_run=processing_run,
        evidence_references=(
            EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),
            *evidence_references,
        ),
        recorded_at=recorded_at,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpSourceQualificationEvidence:
    """Pre-existing source/provider qualification bound to one DJ observation."""

    target_observation_id: InstanceIdentifier
    qualification_observation: ScientificMeasurementObservation
    qualification_reference: RegistryReference

    def __post_init__(self) -> None:
        if self.target_observation_id.instance_type != "observation":
            raise ValueError("target_observation_id must identify an observation")
        _require_instance(
            self.qualification_observation,
            ScientificMeasurementObservation,
            "qualification_observation",
        )
        _require_instance(
            self.qualification_reference, RegistryReference, "qualification_reference"
        )
        if self.qualification_reference != DROP_JUMP_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("qualification reference is not the registered DJ source rule")
        value = self.qualification_observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("DJ qualification must carry a categorical source result")
        try:
            DropJumpQualificationStatus(value.category)
        except ValueError as exc:
            raise ValueError("DJ qualification category is not registered") from exc
        if self.qualification_observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("DJ qualification must remain source/provider-origin")
        if self.qualification_observation.result.status is not ResultStatus.VALID:
            raise ValueError("DJ qualification observation must be valid")
        if any(
            not isinstance(artifact, DropJumpSourceArtifact)
            or not artifact.immutable
            or artifact.status is not DropJumpArtifactStatus.VERIFIED
            for artifact in self.qualification_observation.provenance.source_artifacts
        ):
            raise ValueError("DJ qualification must preserve verified source artifacts")
        if any(
            not isinstance(acquisition, DropJumpAcquisitionRecord)
            for acquisition in self.qualification_observation.provenance.acquisitions
        ):
            raise ValueError("DJ qualification must preserve typed acquisitions")
        identity = self.qualification_observation.identity
        if not isinstance(identity, DropJumpMeasurementIdentity):
            raise ValueError("DJ qualification requires a DJ measurement identity")
        if identity.semantic.measurand != DROP_JUMP_QUALIFICATION_MEASURAND:
            raise ValueError("DJ qualification has the wrong measurand")
        if identity.semantic.metric_definition != DROP_JUMP_QUALIFICATION_METRIC:
            raise ValueError("DJ qualification has the wrong metric")
        if identity.processing.registered_operation != DROP_JUMP_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("DJ qualification has the wrong operation")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if parameters.get("target_observation_id") != self.target_observation_id.qualified:
            raise ValueError("DJ qualification target is not preserved in identity")
        if parameters.get("source_status") != self.status.value:
            raise ValueError("DJ qualification status is not preserved in identity")

    @property
    def status(self) -> DropJumpQualificationStatus:
        value = self.qualification_observation.result.value
        assert isinstance(value, CategoricalValue)
        return DropJumpQualificationStatus(value.category)

    @property
    def source_observation_id(self) -> InstanceIdentifier:
        return self.qualification_observation.observation_id


def build_drop_jump_qualification_source_observation(
    *,
    target_observation: ScientificMeasurementObservation,
    reported_status: DropJumpQualificationStatus,
    source_artifact: DropJumpSourceArtifact,
    acquisition: DropJumpAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    adjudication_rule: RegistryReference | None = None,
    reason_codes: tuple[str, ...] = (),
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Ingest source/provider qualification; it does not itself normalize it."""

    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    _require_enum(reported_status, DropJumpQualificationStatus, "reported_status")
    _require_enum(value_origin, ValueOrigin, "value_origin")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("DJ qualification ingestion requires source/provider origin")
    _require_verified_artifact(source_artifact)
    _require_instance(acquisition, DropJumpAcquisitionRecord, "acquisition")
    if adjudication_rule is not None:
        _require_instance(adjudication_rule, RegistryReference, "adjudication_rule")
    target_identity = target_observation.identity
    if not isinstance(target_identity, DropJumpMeasurementIdentity):
        raise ValueError("target observation requires a DJ measurement identity")
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"drop-jump-qualification:{target_observation.observation_id.value}"
    )
    if observation_id == target_observation.observation_id:
        raise ValueError("DJ qualification observation must differ from target")
    _require_tuple_items(reason_codes, str, "reason_codes")
    parameters = (
        MetadataEntry("target_observation_id", target_observation.observation_id.qualified),
        MetadataEntry("source_status", reported_status.value),
        MetadataEntry("reason_codes", canonical_json(reason_codes)),
        *(
            (MetadataEntry("adjudication_rule", adjudication_rule.stable_id),)
            if adjudication_rule is not None
            else ()
        ),
    )
    identity = DropJumpMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"drop-jump-qualification:{observation_id.value}",
            DROP_JUMP_REGISTRY_VERSION,
        ),
        semantic=DropJumpSemanticIdentity(
            construct=target_identity.semantic.construct,
            test_family=DROP_JUMP_TEST_FAMILY,
            protocol=target_identity.semantic.protocol,
            measurand=DROP_JUMP_QUALIFICATION_MEASURAND,
            metric_definition=DROP_JUMP_QUALIFICATION_METRIC,
            protocol_identity=target_identity.semantic.protocol_identity,
        ),
        acquisition=DropJumpAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=source_artifact.artifact_id,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            acquisition_instance_id=acquisition.acquisition_id,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=acquisition.timebase,
            axis_or_frame=acquisition.axis_or_frame,
        ),
        processing=DropJumpProcessingIdentity(
            registered_operation=DROP_JUMP_SOURCE_QUALIFICATION_OPERATION,
            method_parameters=parameters,
            processing_state=_source_processing_state(value_origin),
            provider_algorithm=adjudication_rule,
        ),
        version=VersionIdentity(
            processing_method=DROP_JUMP_SOURCE_QUALIFICATION_OPERATION,
            method_registry_version=DROP_JUMP_REGISTRY_VERSION,
            software_version=DROP_JUMP_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"drop-jump-qualification:{observation_id.value}"),
        value=CategoricalValue(reported_status.value),
        unit=None,
        classification=ScientificClassification(value_origin, ()),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    return build_drop_jump_source_observation(
        observation_id=observation_id,
        context=target_observation.context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )


def normalize_drop_jump_qualification(
    source_observation: ScientificMeasurementObservation,
    target_observation: ScientificMeasurementObservation,
) -> DropJumpSourceQualificationEvidence:
    """Normalize and validate pre-existing DJ qualification evidence."""

    _require_instance(source_observation, ScientificMeasurementObservation, "source_observation")
    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    if source_observation.observation_id == target_observation.observation_id:
        raise ValueError("DJ qualification observation must differ from target")
    source_identity = source_observation.identity
    target_identity = target_observation.identity
    if not isinstance(source_identity, DropJumpMeasurementIdentity):
        raise ValueError("DJ qualification source requires DJ identity")
    if not isinstance(target_identity, DropJumpMeasurementIdentity):
        raise ValueError("DJ target requires DJ identity")
    if (
        source_identity.semantic.construct != target_identity.semantic.construct
        or source_identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
        or target_identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
        or source_identity.semantic.protocol != target_identity.semantic.protocol
        or source_identity.semantic.protocol_identity != target_identity.semantic.protocol_identity
    ):
        raise ValueError("DJ qualification source is bound to a different scientific target")
    if source_observation.context != target_observation.context:
        raise ValueError("DJ qualification source context does not match target")
    target_artifacts = {
        item.artifact_id: item for item in target_observation.provenance.source_artifacts
    }
    source_artifacts = {
        item.artifact_id: item for item in source_observation.provenance.source_artifacts
    }
    if not source_artifacts or not set(source_artifacts).issubset(target_artifacts):
        raise ValueError("DJ qualification source is not bound to target artifacts")
    if any(target_artifacts[key] != value for key, value in source_artifacts.items()):
        raise ValueError("DJ qualification artifact content was tampered")
    target_acquisitions = {
        item.acquisition_id: item for item in target_observation.provenance.acquisitions
    }
    source_acquisitions = {
        item.acquisition_id: item for item in source_observation.provenance.acquisitions
    }
    if not source_acquisitions or not set(source_acquisitions).issubset(target_acquisitions):
        raise ValueError("DJ qualification source is not bound to target acquisitions")
    if any(target_acquisitions[key] != value for key, value in source_acquisitions.items()):
        raise ValueError("DJ qualification acquisition content was tampered")
    evidence = DropJumpSourceQualificationEvidence(
        target_observation_id=target_observation.observation_id,
        qualification_observation=source_observation,
        qualification_reference=DROP_JUMP_SOURCE_QUALIFICATION_OPERATION,
    )
    if evidence.status is DropJumpQualificationStatus.UNKNOWN:
        raise ValueError("DJ qualification source must report QUALIFIED or REJECTED")
    return evidence


def require_qualified_drop_jump(
    evidence: DropJumpSourceQualificationEvidence,
    target_observation: ScientificMeasurementObservation,
) -> None:
    """Reject caller-minted or rebound DJ qualification evidence."""

    if not isinstance(evidence, DropJumpSourceQualificationEvidence):
        raise ValueError("typed DJ source qualification evidence is required")
    normalized = normalize_drop_jump_qualification(
        evidence.qualification_observation, target_observation
    )
    if normalized != evidence:
        raise ValueError("DJ source qualification evidence was rebound or tampered")
    if evidence.status is not DropJumpQualificationStatus.QUALIFIED:
        raise ValueError("DJ source observation is not qualified")


__all__ = [
    "DropJumpSourceQualificationEvidence",
    "build_drop_jump_qualification_source_observation",
    "build_drop_jump_source_observation",
    "normalize_drop_jump_qualification",
    "require_qualified_drop_jump",
]
