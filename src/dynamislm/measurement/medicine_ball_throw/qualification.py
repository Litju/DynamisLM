"""MBT source observation, trajectory evidence and qualification boundaries."""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, replace
from itertools import pairwise

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    VersionIdentity,
    _require_enum,
    _require_instance,
)
from dynamislm.measurement.medicine_ball_throw.identity import (
    MBTArtifactStatus,
    MBTCoordinateEvidence,
    MBTCoordinateSourceEvidence,
    MBTProcessingState,
    MBTQualificationStatus,
    MBTReleaseEvent,
    MBTReleaseEventSourceEvidence,
    MBTSensorModality,
    MBTTimebase,
    MedicineBallThrowAcquisitionIdentity,
    MedicineBallThrowAcquisitionRecord,
    MedicineBallThrowMeasurementIdentity,
    MedicineBallThrowProcessingIdentity,
    MedicineBallThrowProtocolIdentity,
    MedicineBallThrowSemanticIdentity,
    MedicineBallThrowSourceArtifact,
)
from dynamislm.measurement.medicine_ball_throw.registry import (
    MBT_COORDINATE_QUALIFICATION_RULE,
    MBT_COORDINATE_SOURCE_OPERATION,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC,
    MBT_QUALIFICATION_MEASURAND,
    MBT_QUALIFICATION_METRIC,
    MBT_REGISTRY_VERSION,
    MBT_RELEASE_EVENT_QUALIFICATION_RULE,
    MBT_RELEASE_EVENT_SOURCE_OPERATION,
    MBT_RELEASE_VELOCITY_SCHEMA,
    MBT_RELEASE_VELOCITY_SOURCE_OPERATION,
    MBT_SOFTWARE_VERSION,
    MBT_SOURCE_DISTANCE_OPERATION,
    MBT_SOURCE_QUALIFICATION_OPERATION,
    MBT_THROW_DISTANCE_MEASURAND,
    MBT_THROW_DISTANCE_METRIC,
    MEDICINE_BALL_THROW_CONSTRUCT,
    MEDICINE_BALL_THROW_TEST_FAMILY,
    METER,
    METERS_PER_SECOND,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    CategoricalValue,
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
)
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _require_verified_artifact(artifact: MedicineBallThrowSourceArtifact) -> None:
    if not isinstance(artifact, MedicineBallThrowSourceArtifact):
        raise ValueError("MBT source artifact must use its typed artifact contract")
    if not artifact.immutable or artifact.status is not MBTArtifactStatus.VERIFIED:
        raise ValueError("MBT source artifact must be immutable and verified")


def _validate_binding(
    identity: MedicineBallThrowMeasurementIdentity,
    artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
) -> None:
    if identity.acquisition.raw_artifact != artifact.artifact_id:
        raise ValueError("MBT identity raw artifact does not match source artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("MBT identity acquisition does not match acquisition record")
    if acquisition.source_artifact_id != artifact.artifact_id:
        raise ValueError("MBT acquisition does not reference source artifact")
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
        raise ValueError("MBT identity and acquisition record do not describe the same system")


def _build_source_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: MedicineBallThrowMeasurementIdentity,
    result: MeasurementResult,
    source_artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
    recorded_at: datetime_module.datetime | None,
) -> ScientificMeasurementObservation:
    _require_verified_artifact(source_artifact)
    _require_instance(context, ObservationContext, "context")
    _require_instance(identity, MedicineBallThrowMeasurementIdentity, "identity")
    _require_instance(result, MeasurementResult, "result")
    _require_instance(acquisition, MedicineBallThrowAcquisitionRecord, "acquisition")
    if observation_id.instance_type != "observation":
        raise ValueError("MBT observation ID must identify an observation")
    _validate_binding(identity, source_artifact, acquisition)
    protocol = identity.semantic.protocol_identity
    if protocol is not None:
        if protocol.device is not None and protocol.device != acquisition.device:
            raise ValueError("MBT protocol device does not match acquisition")
        if protocol.provider is not None and protocol.provider != acquisition.provider:
            raise ValueError("MBT protocol provider does not match acquisition")
        if (
            protocol.sensor_modality is not MBTSensorModality.UNKNOWN
            and protocol.sensor_modality is not acquisition.sensor_modality
        ):
            raise ValueError("MBT protocol modality does not match acquisition")
        if protocol.timebase is not None and protocol.timebase != acquisition.timebase:
            raise ValueError("MBT protocol timebase does not match acquisition")
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"mbt-source:{observation_id.value}"
        ),
        source_artifact_ids=(source_artifact.artifact_id,),
        method=identity.version.processing_method,
        parameters=identity.processing.method_parameters,
        software_version=identity.version.software_version,
        output_entity_id=observation_id,
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        provenance=Provenance(
            provenance_id=InstanceIdentifier("provenance", observation_id.value),
            source_artifacts=(source_artifact,),
            acquisitions=(acquisition,),
            processing_runs=(run,),
            lineage_edges=(
                LineageEdge(
                    source_artifact.artifact_id.qualified,
                    acquisition.acquisition_id.qualified,
                    LineageRelation.ACQUIRED_AS,
                ),
                LineageEdge(
                    acquisition.acquisition_id.qualified,
                    run.processing_run_id.qualified,
                    LineageRelation.PROCESSED_AS,
                ),
                LineageEdge(
                    run.processing_run_id.qualified,
                    observation_id.qualified,
                    LineageRelation.PRODUCED,
                ),
            ),
            evidence_references=(EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),),
            recorded_at=recorded_at or context.observed_at,
        ),
    )


def build_mbt_source_distance_observation(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    protocol_identity: MedicineBallThrowProtocolIdentity,
    distance_m: float,
    source_artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    method_parameters: tuple[MetadataEntry, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Represent a source-reported/provider-derived exact MBT distance."""

    _require_instance(protocol_identity, MedicineBallThrowProtocolIdentity, "protocol_identity")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("MBT source distance must remain source/provider-origin")
    value = _finite(distance_m, "distance_m")
    if value < 0:
        raise ValueError("distance_m must not be negative")
    parameters = (
        MetadataEntry("source_metric", MBT_THROW_DISTANCE_METRIC.stable_id),
        *method_parameters,
    )
    identity = MedicineBallThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"mbt-distance:{observation_id.value}",
            MBT_REGISTRY_VERSION,
        ),
        semantic=MedicineBallThrowSemanticIdentity(
            construct=MEDICINE_BALL_THROW_CONSTRUCT,
            test_family=MEDICINE_BALL_THROW_TEST_FAMILY,
            protocol=protocol_identity.reference,
            measurand=MBT_THROW_DISTANCE_MEASURAND,
            metric_definition=MBT_THROW_DISTANCE_METRIC,
            protocol_identity=protocol_identity,
        ),
        acquisition=MedicineBallThrowAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=source_artifact.artifact_id,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=acquisition.timebase,
            axis_or_frame=acquisition.axis_or_frame,
            acquisition_instance_id=acquisition.acquisition_id,
        ),
        processing=MedicineBallThrowProcessingIdentity(
            registered_operation=MBT_SOURCE_DISTANCE_OPERATION,
            method_parameters=parameters,
            processing_state=(
                MBTProcessingState.RAW_ACQUIRED
                if value_origin is ValueOrigin.SOURCE_REPORTED
                else MBTProcessingState.PROVIDER_PROCESSED
            ),
            provider_algorithm=None,
            timebase=acquisition.timebase,
        ),
        version=VersionIdentity(
            processing_method=MBT_SOURCE_DISTANCE_OPERATION,
            method_registry_version=MBT_REGISTRY_VERSION,
            software_version=MBT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    return _build_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=ScalarValue(value),
            unit=METER,
            classification=ScientificClassification(value_origin, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )


def _normalize_samples(
    samples: tuple[tuple[float, float], ...],
    label: str,
) -> tuple[tuple[float, float], ...]:
    if not isinstance(samples, tuple) or not samples:
        raise ValueError(f"MBT {label} samples must be a non-empty tuple")
    normalized: list[tuple[float, float]] = []
    for sample in samples:
        if not isinstance(sample, tuple) or len(sample) != 2:
            raise ValueError(f"MBT {label} samples must be (time, value) tuples")
        normalized.append(
            (
                _finite(sample[0], f"{label} sample time"),
                _finite(sample[1], f"{label} sample value"),
            )
        )
    if any(right[0] <= left[0] for left, right in pairwise(normalized)):
        raise ValueError(f"MBT {label} timestamps must increase")
    return tuple(normalized)


def _trajectory_digest(
    trajectory_samples: tuple[tuple[float, float], ...],
    velocity_samples: tuple[tuple[float, float], ...],
    timebase: MBTTimebase,
    coordinate_frame: RegistryReference,
) -> str:
    normalized_trajectory = _normalize_samples(trajectory_samples, "trajectory")
    normalized_velocity = _normalize_samples(velocity_samples, "velocity")
    return canonical_hash(
        {
            "trajectory_samples": normalized_trajectory,
            "velocity_samples": normalized_velocity,
            "timebase": timebase,
            "coordinate_frame": coordinate_frame,
        }
    )


def _coordinate_source_parameters(
    source: MBTCoordinateSourceEvidence,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("source_coordinate_id", source.source_coordinate_id.qualified),
        MetadataEntry("source_context_id", source.source_context_id.qualified),
        MetadataEntry("source_observation_id", source.source_observation_id.qualified),
        MetadataEntry("source_artifact_id", source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", source.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", source.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("protocol_reference", source.protocol_reference.stable_id),
        MetadataEntry("origin_coordinate_m", source.origin_coordinate_m),
        MetadataEntry("endpoint_coordinate_m", source.endpoint_coordinate_m),
        MetadataEntry("coordinate_frame", source.coordinate_frame.stable_id),
        MetadataEntry("origin_convention", source.origin_convention.stable_id),
        MetadataEntry("endpoint_convention", source.endpoint_convention.stable_id),
        MetadataEntry(
            "first_contact_no_roll_convention",
            source.first_contact_no_roll_convention.stable_id,
        ),
        MetadataEntry("first_contact_observed", source.first_contact_observed),
        MetadataEntry("no_roll_observed", source.no_roll_observed),
        MetadataEntry("source_content_digest", source.source_content_digest),
        MetadataEntry("provider", source.provider),
        MetadataEntry("method_parameters", canonical_json(source.method_parameters)),
        MetadataEntry("source_value_origin", source.source_value_origin),
    )


def _validate_coordinate_source_evidence(
    source: MBTCoordinateSourceEvidence,
    source_observation: ScientificMeasurementObservation,
) -> None:
    _require_instance(source, MBTCoordinateSourceEvidence, "coordinate_source_evidence")
    _require_instance(source_observation, ScientificMeasurementObservation, "source_observation")
    identity = source_observation.identity
    if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
        raise ValueError("MBT coordinate source requires MBT identity")
    protocol = identity.semantic.protocol_identity
    if protocol is None:
        raise ValueError("MBT coordinate source requires protocol identity")
    observation_acquisition = next(
        (
            item
            for item in source_observation.provenance.acquisitions
            if item.acquisition_id == source.source_acquisition_id
        ),
        None,
    )
    if not isinstance(observation_acquisition, MedicineBallThrowAcquisitionRecord):
        raise ValueError("MBT coordinate source requires its typed acquisition")
    if (
        source.source_context_id != source_observation.context.context_id
        or source.source_observation_id != source_observation.observation_id
        or source.source_measurement_identity_id != identity.identity_id
        or source.protocol_reference != protocol.reference
        or source.provider != observation_acquisition.provider
        or source.coordinate_frame != observation_acquisition.axis_or_frame
    ):
        raise ValueError("MBT coordinate source is not bound to the source observation")
    if source_observation.result.status is not ResultStatus.VALID:
        raise ValueError("MBT coordinate source observation must be valid")
    if source.source_value_origin != source_observation.result.classification.value_origin.value:
        raise ValueError("MBT coordinate source origin does not match observation")
    if source.processing_method != MBT_COORDINATE_SOURCE_OPERATION:
        raise ValueError("MBT coordinate source processing method is not registered")
    if source.source_artifact_id not in {
        item.artifact_id for item in source_observation.provenance.source_artifacts
    } or source.source_acquisition_id not in {
        item.acquisition_id for item in source_observation.provenance.acquisitions
    }:
        raise ValueError("MBT coordinate source is not bound to source provenance")
    source_artifacts = tuple(
        item
        for item in source.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    source_acquisitions = tuple(
        item
        for item in source.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    observation_artifact = next(
        item
        for item in source_observation.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    observation_acquisition = next(
        item
        for item in source_observation.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    if (
        source_artifacts != (observation_artifact,)
        or source_acquisitions != (observation_acquisition,)
        or not isinstance(observation_artifact, MedicineBallThrowSourceArtifact)
        or not observation_artifact.immutable
        or observation_artifact.status is not MBTArtifactStatus.VERIFIED
    ):
        raise ValueError("MBT coordinate source provenance must preserve verified source objects")
    if source.source_content_digest != observation_artifact.content_digest:
        raise ValueError("MBT coordinate source digest does not match source artifact")
    if protocol.provider is not None and protocol.provider != source.provider:
        raise ValueError("MBT coordinate source provider does not match protocol")
    if protocol.distance_origin_convention != source.origin_convention:
        raise ValueError("MBT coordinate origin convention does not match protocol")
    if protocol.distance_endpoint_convention != source.endpoint_convention:
        raise ValueError("MBT coordinate endpoint convention does not match protocol")
    if protocol.first_contact_no_roll_convention != source.first_contact_no_roll_convention:
        raise ValueError("MBT coordinate contact/no-roll convention does not match protocol")
    run = next(
        (
            item
            for item in source.provenance.processing_runs
            if item.output_entity_id == source.source_coordinate_id
        ),
        None,
    )
    if run is None or run.processing_run_id != source.upstream_processing_run_id:
        raise ValueError("MBT coordinate source provenance must preserve its producing run")
    if run.method != source.processing_method:
        raise ValueError("MBT coordinate source run method does not match processing method")
    if run.parameters != _coordinate_source_parameters(source):
        raise ValueError("MBT coordinate source run parameters do not reproduce")
    for from_id, relation in (
        (source.source_observation_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_artifact_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_acquisition_id.qualified, LineageRelation.DERIVED_FROM),
        (MBT_COORDINATE_QUALIFICATION_RULE.stable_id, LineageRelation.SUPPORTED_BY),
    ):
        if not any(
            edge.from_id == from_id
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is relation
            for edge in source.provenance.lineage_edges
        ):
            raise ValueError("MBT coordinate source provenance omits an authority lineage edge")
    if not any(
        edge.from_id == run.processing_run_id.qualified
        and edge.to_id == source.source_coordinate_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in source.provenance.lineage_edges
    ):
        raise ValueError("MBT coordinate source provenance omits the produced coordinate edge")


def normalize_mbt_coordinate_evidence(
    source: MBTCoordinateSourceEvidence,
    source_observation: ScientificMeasurementObservation,
    coordinate: MBTCoordinateEvidence | None = None,
) -> MBTCoordinateEvidence:
    """Normalize qualified upstream coordinates into distance evidence."""

    _validate_coordinate_source_evidence(source, source_observation)
    normalized = MBTCoordinateEvidence(
        source_observation_id=source.source_observation_id,
        origin_coordinate_m=source.origin_coordinate_m,
        endpoint_coordinate_m=source.endpoint_coordinate_m,
        coordinate_frame=source.coordinate_frame,
        origin_convention=source.origin_convention,
        endpoint_convention=source.endpoint_convention,
        first_contact_no_roll_convention=source.first_contact_no_roll_convention,
        first_contact_observed=source.first_contact_observed,
        no_roll_observed=source.no_roll_observed,
        source_artifact_id=source.source_artifact_id,
        acquisition_id=source.source_acquisition_id,
        source_evidence=source,
    )
    if coordinate is not None and coordinate != normalized:
        raise ValueError("MBT coordinate does not preserve upstream coordinate evidence")
    return normalized


def _release_event_source_parameters(
    source: MBTReleaseEventSourceEvidence,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("source_event_id", source.source_event_id.qualified),
        MetadataEntry("source_context_id", source.source_context_id.qualified),
        MetadataEntry("source_observation_id", source.source_observation_id.qualified),
        MetadataEntry("source_series_id", source.source_series_id.qualified),
        MetadataEntry("source_artifact_id", source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", source.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", source.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("source_series_digest", source.source_series_digest),
        MetadataEntry("source_timebase", canonical_json(source.source_timebase)),
        MetadataEntry("sample_index", source.sample_index),
        MetadataEntry("event_time_s", source.event_time_s),
        MetadataEntry("release_method", source.release_method.stable_id),
        MetadataEntry("coordinate_frame", source.coordinate_frame.stable_id),
        MetadataEntry("protocol_reference", source.protocol_reference.stable_id),
        MetadataEntry("provider", source.provider),
        MetadataEntry("method_parameters", canonical_json(source.method_parameters)),
        MetadataEntry("source_value_origin", source.source_value_origin),
    )


def _validate_release_event_source_evidence(
    source: MBTReleaseEventSourceEvidence,
    observation: ScientificMeasurementObservation,
    release_event: MBTReleaseEvent,
    protocol: MedicineBallThrowProtocolIdentity,
    timebase: MBTTimebase,
    coordinate_frame: RegistryReference,
    source_series_digest: str,
) -> None:
    _require_instance(source, MBTReleaseEventSourceEvidence, "release_event_source_evidence")
    identity = observation.identity
    if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
        raise ValueError("MBT release source requires MBT identity")
    observation_acquisition = next(
        (
            item
            for item in observation.provenance.acquisitions
            if item.acquisition_id == source.source_acquisition_id
        ),
        None,
    )
    if not isinstance(observation_acquisition, MedicineBallThrowAcquisitionRecord):
        raise ValueError("MBT release source requires its typed acquisition")
    if (
        source != release_event.source_evidence
        or source.source_context_id != observation.context.context_id
        or source.source_observation_id != observation.observation_id
        or source.source_measurement_identity_id != identity.identity_id
        or source.protocol_reference != protocol.reference
        or source.source_timebase != timebase
        or source.source_series_digest != source_series_digest
        or source.coordinate_frame != coordinate_frame
        or source.provider != observation_acquisition.provider
    ):
        raise ValueError("MBT release event source is not bound to the exact observation")
    if observation.result.status is not ResultStatus.VALID:
        raise ValueError("MBT release source observation must be valid")
    if source.source_value_origin != observation.result.classification.value_origin.value:
        raise ValueError("MBT release source origin does not match observation")
    if source.processing_method != MBT_RELEASE_EVENT_SOURCE_OPERATION:
        raise ValueError("MBT release event source processing method is not registered")
    if protocol.provider is not None and source.provider != protocol.provider:
        raise ValueError("MBT release event source provider does not match protocol")
    if source.source_artifact_id not in {
        item.artifact_id for item in observation.provenance.source_artifacts
    } or source.source_acquisition_id not in {
        item.acquisition_id for item in observation.provenance.acquisitions
    }:
        raise ValueError("MBT release event source is not bound to source provenance")
    source_artifact = next(
        item
        for item in observation.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    if not isinstance(source_artifact, MedicineBallThrowSourceArtifact):
        raise ValueError("MBT release source must preserve its typed artifact")
    if (
        not source_artifact.immutable
        or source_artifact.status is not MBTArtifactStatus.VERIFIED
        or source_artifact.content_digest != source_series_digest
    ):
        raise ValueError("MBT release source artifact digest is not verified")
    source_artifacts = tuple(
        item
        for item in source.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    source_acquisitions = tuple(
        item
        for item in source.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    observation_acquisition = next(
        item
        for item in observation.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    if source_artifacts != (source_artifact,) or source_acquisitions != (observation_acquisition,):
        raise ValueError("MBT release source provenance does not preserve source objects")
    run = next(
        (
            item
            for item in source.provenance.processing_runs
            if item.output_entity_id == source.source_event_id
        ),
        None,
    )
    if run is None or run.processing_run_id != source.upstream_processing_run_id:
        raise ValueError("MBT release source provenance must preserve its producing run")
    if run.method != source.processing_method:
        raise ValueError("MBT release source run method does not match processing method")
    if run.parameters != _release_event_source_parameters(source):
        raise ValueError("MBT release source run parameters do not reproduce")
    for from_id, relation in (
        (source.source_observation_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_series_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_artifact_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_acquisition_id.qualified, LineageRelation.DERIVED_FROM),
        (MBT_RELEASE_EVENT_QUALIFICATION_RULE.stable_id, LineageRelation.SUPPORTED_BY),
    ):
        if not any(
            edge.from_id == from_id
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is relation
            for edge in source.provenance.lineage_edges
        ):
            raise ValueError("MBT release source provenance omits an authority lineage edge")
    if not any(
        edge.from_id == run.processing_run_id.qualified
        and edge.to_id == source.source_event_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in source.provenance.lineage_edges
    ):
        raise ValueError("MBT release source provenance omits the produced event edge")


def _merge_provenance(left: Provenance, right: Provenance) -> Provenance:
    artifacts = list(left.source_artifacts)
    for artifact_item in right.source_artifacts:
        prior_artifact = next(
            (value for value in artifacts if value.artifact_id == artifact_item.artifact_id),
            None,
        )
        if prior_artifact is not None and prior_artifact != artifact_item:
            raise ValueError("MBT provenance contains conflicting source artifacts")
        if prior_artifact is None:
            artifacts.append(artifact_item)
    acquisitions = list(left.acquisitions)
    for acquisition_item in right.acquisitions:
        prior_acquisition = next(
            (
                value
                for value in acquisitions
                if value.acquisition_id == acquisition_item.acquisition_id
            ),
            None,
        )
        if prior_acquisition is not None and prior_acquisition != acquisition_item:
            raise ValueError("MBT provenance contains conflicting acquisitions")
        if prior_acquisition is None:
            acquisitions.append(acquisition_item)
    runs = list(left.processing_runs)
    for run_item in right.processing_runs:
        prior_run = next(
            (value for value in runs if value.processing_run_id == run_item.processing_run_id),
            None,
        )
        if prior_run is not None and prior_run != run_item:
            raise ValueError("MBT provenance contains conflicting processing runs")
        if prior_run is None:
            runs.append(run_item)
    edges = list(left.lineage_edges)
    for edge_item in right.lineage_edges:
        if edge_item not in edges:
            edges.append(edge_item)
    evidence = list(left.evidence_references)
    for evidence_item in right.evidence_references:
        if evidence_item not in evidence:
            evidence.append(evidence_item)
    traceability = list(left.metrological_traceability)
    for traceability_item in right.metrological_traceability:
        if traceability_item not in traceability:
            traceability.append(traceability_item)
    return Provenance(
        provenance_id=left.provenance_id,
        source_artifacts=tuple(artifacts),
        acquisitions=tuple(acquisitions),
        processing_runs=tuple(runs),
        lineage_edges=tuple(edges),
        evidence_references=tuple(evidence),
        metrological_traceability=tuple(traceability),
        recorded_at=left.recorded_at or right.recorded_at,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTReleaseVelocityEvidence:
    """Qualified trajectory and velocity samples bound to an explicit release event."""

    observation: ScientificMeasurementObservation
    release_event: MBTReleaseEvent
    trajectory_samples: tuple[tuple[float, float], ...]
    velocity_samples: tuple[tuple[float, float], ...]
    timebase: MBTTimebase
    coordinate_frame: RegistryReference
    velocity_definition: RegistryReference
    source_series_digest: str

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.release_event, MBTReleaseEvent, "release_event")
        _require_instance(self.timebase, MBTTimebase, "timebase")
        _require_instance(self.coordinate_frame, RegistryReference, "coordinate_frame")
        _require_instance(self.velocity_definition, RegistryReference, "velocity_definition")
        if self.observation.observation_id != self.release_event.source_observation_id:
            raise ValueError("release event must bind the source observation")
        release_source_evidence = self.release_event.source_evidence
        if not isinstance(release_source_evidence, MBTReleaseEventSourceEvidence):
            raise ValueError("release_event.source_evidence must be MBTReleaseEventSourceEvidence")
        identity = self.observation.identity
        if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
            raise ValueError("MBT release evidence requires MBT measurement identity")
        if (
            identity.semantic.measurand != MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND
            or identity.semantic.metric_definition != MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC
        ):
            raise ValueError("MBT release evidence has the wrong measurand or metric")
        if identity.processing.registered_operation != MBT_RELEASE_VELOCITY_SOURCE_OPERATION:
            raise ValueError("MBT release evidence has the wrong source operation")
        if identity.acquisition.raw_artifact != self.release_event.source_artifact_id:
            raise ValueError("MBT release evidence artifact binding is invalid")
        if identity.acquisition.acquisition_instance_id != self.release_event.acquisition_id:
            raise ValueError("MBT release evidence acquisition binding is invalid")
        if identity.acquisition.timebase != self.timebase:
            raise ValueError("MBT release evidence timebase is not preserved")
        if identity.acquisition.axis_or_frame != self.coordinate_frame:
            raise ValueError("MBT release evidence coordinate frame is not preserved")
        if identity.acquisition.source_series_digest != self.source_series_digest:
            raise ValueError("MBT release evidence series digest is not preserved in identity")
        if self.release_event.source_artifact_id not in {
            artifact.artifact_id for artifact in self.observation.provenance.source_artifacts
        }:
            raise ValueError("MBT release event artifact is absent from provenance")
        if self.release_event.acquisition_id not in {
            acquisition.acquisition_id for acquisition in self.observation.provenance.acquisitions
        }:
            raise ValueError("MBT release event acquisition is absent from provenance")
        if not isinstance(self.trajectory_samples, tuple) or not isinstance(
            self.velocity_samples, tuple
        ):
            raise ValueError("MBT trajectory/velocity samples must be immutable tuples")
        if (
            len(self.trajectory_samples) != len(self.velocity_samples)
            or not self.trajectory_samples
        ):
            raise ValueError("MBT trajectory and velocity samples must have equal non-zero length")
        for samples, label in (
            (self.trajectory_samples, "trajectory"),
            (self.velocity_samples, "velocity"),
        ):
            normalized = _normalize_samples(samples, label)
            if any(
                self.timebase.time_at(index) != sample[0] for index, sample in enumerate(normalized)
            ):
                raise ValueError(f"MBT {label} timestamps must match timebase")
            object.__setattr__(self, f"{label}_samples", normalized)
        digest = _trajectory_digest(
            self.trajectory_samples, self.velocity_samples, self.timebase, self.coordinate_frame
        )
        if self.source_series_digest != digest or self.release_event.source_series_digest != digest:
            raise ValueError("MBT release evidence has an invalid source-series digest")
        index = self.release_event.sample_index
        if index >= len(self.velocity_samples):
            raise ValueError("MBT release index is outside source samples")
        if self.velocity_samples[index][0] != self.release_event.event_time_s:
            raise ValueError("MBT release event must equal an exact velocity sample timestamp")
        if self.release_event.coordinate_frame != self.coordinate_frame:
            raise ValueError("MBT release event frame does not match trajectory evidence")
        if self.release_event.release_method != self.velocity_definition:
            raise ValueError("MBT release event method does not match velocity definition")
        source_artifact = next(
            (
                artifact
                for artifact in self.observation.provenance.source_artifacts
                if artifact.artifact_id == self.release_event.source_artifact_id
            ),
            None,
        )
        if not isinstance(source_artifact, MedicineBallThrowSourceArtifact):
            raise ValueError("MBT release evidence must preserve its typed source artifact")
        if source_artifact.content_digest != self.source_series_digest:
            raise ValueError("MBT release source artifact digest does not match source series")
        if self.observation.result.value != StructuredOutputReference(
            artifact_id=self.release_event.source_artifact_id,
            schema=MBT_RELEASE_VELOCITY_SCHEMA,
        ):
            raise ValueError(
                "MBT release observation must reference the qualified trajectory artifact"
            )
        if self.observation.result.unit != METERS_PER_SECOND:
            raise ValueError("MBT release observation must use m/s")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("MBT release source evidence must remain source/provider-origin")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("MBT release source observation must be valid")
        protocol = identity.semantic.protocol_identity
        if protocol is None:
            raise ValueError("MBT release evidence requires protocol identity")
        _validate_release_event_source_evidence(
            release_source_evidence,
            self.observation,
            self.release_event,
            protocol,
            self.timebase,
            self.coordinate_frame,
            self.source_series_digest,
        )

    @property
    def release_velocity_m_per_s(self) -> float:
        return self.velocity_samples[self.release_event.sample_index][1]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTSourceQualificationEvidence:
    target_observation_id: InstanceIdentifier
    qualification_observation: ScientificMeasurementObservation
    qualification_reference: RegistryReference

    def __post_init__(self) -> None:
        if self.target_observation_id.instance_type != "observation":
            raise ValueError("MBT qualification target must identify an observation")
        _require_instance(
            self.qualification_observation,
            ScientificMeasurementObservation,
            "qualification_observation",
        )
        if self.qualification_reference != MBT_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("MBT qualification reference is not registered")
        value = self.qualification_observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("MBT qualification must be categorical")
        try:
            MBTQualificationStatus(value.category)
        except ValueError as exc:
            raise ValueError("MBT qualification category is not registered") from exc
        if self.qualification_observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("MBT qualification must remain source/provider-origin")
        if self.qualification_observation.result.status is not ResultStatus.VALID:
            raise ValueError("MBT qualification observation must be valid")
        identity = self.qualification_observation.identity
        if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
            raise ValueError("MBT qualification requires MBT identity")
        if (
            identity.semantic.measurand != MBT_QUALIFICATION_MEASURAND
            or identity.semantic.metric_definition != MBT_QUALIFICATION_METRIC
        ):
            raise ValueError("MBT qualification has the wrong measurand/metric")
        if any(
            not isinstance(artifact, MedicineBallThrowSourceArtifact)
            or not artifact.immutable
            or artifact.status is not MBTArtifactStatus.VERIFIED
            for artifact in self.qualification_observation.provenance.source_artifacts
        ):
            raise ValueError("MBT qualification must preserve verified source artifacts")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if identity.processing.registered_operation != MBT_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("MBT qualification has the wrong operation")
        if parameters.get("target_observation_id") != self.target_observation_id.qualified:
            raise ValueError("MBT qualification target is not preserved")
        if parameters.get("source_status") != self.status.value:
            raise ValueError("MBT qualification status is not preserved")

    @property
    def status(self) -> MBTQualificationStatus:
        value = self.qualification_observation.result.value
        assert isinstance(value, CategoricalValue)
        return MBTQualificationStatus(value.category)


def build_mbt_release_velocity_evidence(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    protocol_identity: MedicineBallThrowProtocolIdentity,
    release_event: MBTReleaseEvent,
    trajectory_samples: tuple[tuple[float, float], ...],
    velocity_samples: tuple[tuple[float, float], ...],
    timebase: MBTTimebase,
    coordinate_frame: RegistryReference,
    velocity_definition: RegistryReference,
    source_artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.PROVIDER_DERIVED,
    recorded_at: datetime_module.datetime | None = None,
) -> MBTReleaseVelocityEvidence:
    """Create qualified instrumented release evidence from exact samples."""

    _require_instance(protocol_identity, MedicineBallThrowProtocolIdentity, "protocol_identity")
    _require_instance(release_event, MBTReleaseEvent, "release_event")
    _require_instance(timebase, MBTTimebase, "timebase")
    release_source_evidence = release_event.source_evidence
    if not isinstance(release_source_evidence, MBTReleaseEventSourceEvidence):
        raise ValueError("release_event.source_evidence must be MBTReleaseEventSourceEvidence")
    if release_event.source_observation_id != observation_id:
        raise ValueError("MBT release event source observation must match observation_id")
    if release_event.source_artifact_id != source_artifact.artifact_id:
        raise ValueError("MBT release event artifact must match source artifact")
    if release_event.acquisition_id != acquisition.acquisition_id:
        raise ValueError("MBT release event acquisition must match acquisition record")
    if release_event.release_method != velocity_definition:
        raise ValueError("MBT release event method must match velocity definition")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("MBT release evidence must remain source/provider-origin")
    normalized_trajectory = _normalize_samples(trajectory_samples, "trajectory")
    normalized_velocity = _normalize_samples(velocity_samples, "velocity")
    digest = _trajectory_digest(
        normalized_trajectory, normalized_velocity, timebase, coordinate_frame
    )
    if release_event.source_series_digest != digest:
        raise ValueError("release event digest does not match exact instrumented samples")
    _require_verified_artifact(source_artifact)
    if source_artifact.content_digest != digest:
        raise ValueError("MBT source artifact digest must match exact trajectory evidence")
    _require_instance(acquisition, MedicineBallThrowAcquisitionRecord, "acquisition")
    parameters = (
        MetadataEntry("source_series_digest", digest),
        MetadataEntry("release_event_id", release_event.event_id.qualified),
        MetadataEntry("velocity_definition", velocity_definition.stable_id),
    )
    identity = MedicineBallThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"mbt-release:{observation_id.value}",
            MBT_REGISTRY_VERSION,
        ),
        semantic=MedicineBallThrowSemanticIdentity(
            construct=MEDICINE_BALL_THROW_CONSTRUCT,
            test_family=MEDICINE_BALL_THROW_TEST_FAMILY,
            protocol=protocol_identity.reference,
            measurand=MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND,
            metric_definition=MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC,
            protocol_identity=protocol_identity,
        ),
        acquisition=MedicineBallThrowAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=source_artifact.artifact_id,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=timebase,
            axis_or_frame=coordinate_frame,
            acquisition_instance_id=acquisition.acquisition_id,
            source_series_digest=digest,
        ),
        processing=MedicineBallThrowProcessingIdentity(
            registered_operation=MBT_RELEASE_VELOCITY_SOURCE_OPERATION,
            method_parameters=parameters,
            processing_state=(
                MBTProcessingState.RAW_ACQUIRED
                if value_origin is ValueOrigin.SOURCE_REPORTED
                else MBTProcessingState.PROVIDER_PROCESSED
            ),
            provider_algorithm=velocity_definition,
            timebase=timebase,
        ),
        version=VersionIdentity(
            processing_method=MBT_RELEASE_VELOCITY_SOURCE_OPERATION,
            method_registry_version=MBT_REGISTRY_VERSION,
            software_version=MBT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    observation = _build_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=StructuredOutputReference(
                artifact_id=source_artifact.artifact_id,
                schema=MBT_RELEASE_VELOCITY_SCHEMA,
            ),
            unit=METERS_PER_SECOND,
            classification=ScientificClassification(value_origin, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )
    _validate_release_event_source_evidence(
        release_source_evidence,
        observation,
        release_event,
        protocol_identity,
        timebase,
        coordinate_frame,
        digest,
    )
    observation = replace(
        observation,
        provenance=_merge_provenance(observation.provenance, release_source_evidence.provenance),
    )
    return MBTReleaseVelocityEvidence(
        observation=observation,
        release_event=release_event,
        trajectory_samples=normalized_trajectory,
        velocity_samples=normalized_velocity,
        timebase=timebase,
        coordinate_frame=coordinate_frame,
        velocity_definition=velocity_definition,
        source_series_digest=digest,
    )


def build_mbt_qualification_source_observation(
    *,
    target_observation: ScientificMeasurementObservation,
    reported_status: MBTQualificationStatus,
    source_artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    output_observation_id: InstanceIdentifier | None = None,
    reason_codes: tuple[str, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    _require_enum(reported_status, MBTQualificationStatus, "reported_status")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("MBT qualification source origin is invalid")
    _require_verified_artifact(source_artifact)
    _require_instance(acquisition, MedicineBallThrowAcquisitionRecord, "acquisition")
    target_identity = target_observation.identity
    if not isinstance(target_identity, MedicineBallThrowMeasurementIdentity):
        raise ValueError("MBT target requires MBT identity")
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"mbt-qualification:{target_observation.observation_id.value}"
    )
    if observation_id == target_observation.observation_id:
        raise ValueError("MBT qualification observation must differ from target")
    parameters = (
        MetadataEntry("target_observation_id", target_observation.observation_id.qualified),
        MetadataEntry("source_status", reported_status.value),
        MetadataEntry("reason_codes", canonical_json(reason_codes)),
    )
    identity = MedicineBallThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"mbt-qualification:{observation_id.value}",
            MBT_REGISTRY_VERSION,
        ),
        semantic=MedicineBallThrowSemanticIdentity(
            construct=target_identity.semantic.construct,
            test_family=MEDICINE_BALL_THROW_TEST_FAMILY,
            protocol=target_identity.semantic.protocol,
            measurand=MBT_QUALIFICATION_MEASURAND,
            metric_definition=MBT_QUALIFICATION_METRIC,
            protocol_identity=target_identity.semantic.protocol_identity,
        ),
        acquisition=MedicineBallThrowAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=source_artifact.artifact_id,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=acquisition.timebase,
            axis_or_frame=acquisition.axis_or_frame,
            acquisition_instance_id=acquisition.acquisition_id,
        ),
        processing=MedicineBallThrowProcessingIdentity(
            registered_operation=MBT_SOURCE_QUALIFICATION_OPERATION,
            method_parameters=parameters,
            processing_state=(
                MBTProcessingState.RAW_ACQUIRED
                if value_origin is ValueOrigin.SOURCE_REPORTED
                else MBTProcessingState.PROVIDER_PROCESSED
            ),
            timebase=acquisition.timebase,
        ),
        version=VersionIdentity(
            processing_method=MBT_SOURCE_QUALIFICATION_OPERATION,
            method_registry_version=MBT_REGISTRY_VERSION,
            software_version=MBT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    return _build_source_observation(
        observation_id=observation_id,
        context=target_observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"mbt-qualification:{observation_id.value}"),
            value=CategoricalValue(reported_status.value),
            unit=None,
            classification=ScientificClassification(value_origin, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )


def normalize_mbt_qualification(
    source_observation: ScientificMeasurementObservation,
    target_observation: ScientificMeasurementObservation,
) -> MBTSourceQualificationEvidence:
    _require_instance(source_observation, ScientificMeasurementObservation, "source_observation")
    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    if source_observation.context != target_observation.context:
        raise ValueError("MBT qualification context does not match target")
    source_identity = source_observation.identity
    target_identity = target_observation.identity
    if not isinstance(source_identity, MedicineBallThrowMeasurementIdentity) or not isinstance(
        target_identity, MedicineBallThrowMeasurementIdentity
    ):
        raise ValueError("MBT qualification and target require MBT identities")
    if source_identity.semantic.protocol_identity != target_identity.semantic.protocol_identity:
        raise ValueError("MBT qualification protocol does not match target")
    target_artifacts = {
        item.artifact_id: item for item in target_observation.provenance.source_artifacts
    }
    source_artifacts = {
        item.artifact_id: item for item in source_observation.provenance.source_artifacts
    }
    if not source_artifacts or not set(source_artifacts).issubset(target_artifacts):
        raise ValueError("MBT qualification artifacts are not bound to target")
    if any(target_artifacts[key] != value for key, value in source_artifacts.items()):
        raise ValueError("MBT qualification artifact content was tampered")
    target_acquisitions = {
        item.acquisition_id: item for item in target_observation.provenance.acquisitions
    }
    source_acquisitions = {
        item.acquisition_id: item for item in source_observation.provenance.acquisitions
    }
    if not source_acquisitions or not set(source_acquisitions).issubset(target_acquisitions):
        raise ValueError("MBT qualification acquisitions are not bound to target")
    if any(target_acquisitions[key] != value for key, value in source_acquisitions.items()):
        raise ValueError("MBT qualification acquisition content was tampered")
    evidence = MBTSourceQualificationEvidence(
        target_observation_id=target_observation.observation_id,
        qualification_observation=source_observation,
        qualification_reference=MBT_SOURCE_QUALIFICATION_OPERATION,
    )
    if evidence.status is MBTQualificationStatus.UNKNOWN:
        raise ValueError("MBT source qualification must report QUALIFIED or REJECTED")
    return evidence


def require_qualified_mbt(
    evidence: MBTSourceQualificationEvidence,
    target_observation: ScientificMeasurementObservation,
) -> None:
    if not isinstance(evidence, MBTSourceQualificationEvidence):
        raise ValueError("typed MBT source qualification evidence is required")
    normalized = normalize_mbt_qualification(evidence.qualification_observation, target_observation)
    if normalized != evidence:
        raise ValueError("MBT qualification evidence was rebound or tampered")
    if evidence.status is not MBTQualificationStatus.QUALIFIED:
        raise ValueError("MBT source observation is not qualified")


__all__ = [
    "MBTReleaseVelocityEvidence",
    "MBTSourceQualificationEvidence",
    "build_mbt_qualification_source_observation",
    "build_mbt_release_velocity_evidence",
    "build_mbt_source_distance_observation",
    "normalize_mbt_coordinate_evidence",
    "normalize_mbt_qualification",
    "require_qualified_mbt",
]
