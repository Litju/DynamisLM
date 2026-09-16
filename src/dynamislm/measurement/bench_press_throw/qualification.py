"""BPT source-series, provider-value and qualification boundaries."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass

from dynamislm.measurement.bench_press_throw.identity import (
    BenchPressThrowAcquisitionRecord,
    BenchPressThrowMeasurementIdentity,
    BenchPressThrowMetricSupport,
    BenchPressThrowProcessingIdentity,
    BenchPressThrowProtocolIdentity,
    BenchPressThrowSemanticIdentity,
    BenchPressThrowSourceArtifact,
    BenchPressThrowVelocitySeries,
    BPTAcquisitionIdentity,
    BPTArtifactStatus,
    BPTProcessingState,
    BPTQualificationStatus,
    BPTSensorModality,
)
from dynamislm.measurement.bench_press_throw.registry import (
    BPT_BAR_VELOCITY_MEASURAND,
    BPT_CONSTRUCT,
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    BPT_MEAN_POWER_MEASURAND,
    BPT_PEAK_POWER_MEASURAND,
    BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_POWER_METRIC,
    BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_VELOCITY_METRIC,
    BPT_PROVIDER_METRIC_SOURCE_OPERATION,
    BPT_PROVIDER_PEAK_POWER_METRIC,
    BPT_QUALIFICATION_MEASURAND,
    BPT_QUALIFICATION_METRIC,
    BPT_REGISTRY_VERSION,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
    BPT_SOFTWARE_VERSION,
    BPT_SOURCE_QUALIFICATION_OPERATION,
    BPT_SOURCE_VELOCITY_SERIES_OPERATION,
    BPT_TEST_FAMILY,
    BPT_VELOCITY_SERIES_METRIC,
    BPT_VELOCITY_SERIES_SCHEMA,
    METER_PER_SECOND,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
    WATT,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    _require_instance,
)
from dynamislm.measurement.observation import (
    ObservationContext,
    ScientificMeasurementObservation,
)
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
from dynamislm.serialization import canonical_json, register_serializable_type


def _origin_for_series(state: BPTProcessingState) -> ValueOrigin:
    if state is BPTProcessingState.RAW_ACQUIRED:
        return ValueOrigin.SOURCE_REPORTED
    if state in {BPTProcessingState.DEVICE_PROCESSED, BPTProcessingState.PROVIDER_PROCESSED}:
        return ValueOrigin.PROVIDER_DERIVED
    raise ValueError("BPT source series must have raw/device/provider processing state")


def _require_verified_artifact(artifact: BenchPressThrowSourceArtifact) -> None:
    if not isinstance(artifact, BenchPressThrowSourceArtifact):
        raise ValueError("BPT source artifact must use its typed artifact contract")
    if not artifact.immutable or artifact.status is not BPTArtifactStatus.VERIFIED:
        raise ValueError("BPT source artifact must be immutable and verified")


def _validate_acquisition_binding(
    identity: BenchPressThrowMeasurementIdentity,
    artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    series: BenchPressThrowVelocitySeries | None = None,
) -> None:
    if identity.acquisition.raw_artifact != artifact.artifact_id:
        raise ValueError("BPT identity raw artifact does not match source artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("BPT identity acquisition does not match acquisition record")
    if acquisition.source_artifact_id != artifact.artifact_id:
        raise ValueError("BPT acquisition does not reference source artifact")
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
        raise ValueError("BPT identity and acquisition record do not describe the same system")
    if series is not None:
        if (
            identity.acquisition.source_series_digest != series.canonical_content_digest()
            or identity.acquisition.timebase != series.timebase
            or identity.acquisition.device != acquisition.device
        ):
            raise ValueError("BPT source series does not match acquisition identity")
    protocol = identity.semantic.protocol_identity
    if protocol is not None:
        if protocol.device is not None and protocol.device != acquisition.device:
            raise ValueError("BPT protocol device does not match acquisition")
        if protocol.provider is not None and protocol.provider != acquisition.provider:
            raise ValueError("BPT protocol provider does not match acquisition")
        if (
            protocol.sensor_modality is not BPTSensorModality.UNKNOWN
            and protocol.sensor_modality is not acquisition.sensor_modality
        ):
            raise ValueError("BPT protocol modality does not match acquisition")
        if protocol.timebase is not None and protocol.timebase != acquisition.timebase:
            raise ValueError("BPT protocol timebase does not match acquisition")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchPressThrowVelocitySeriesEvidence:
    """Qualified source series plus exact metric-specific support."""

    observation: ScientificMeasurementObservation
    identity: BenchPressThrowMeasurementIdentity
    series: BenchPressThrowVelocitySeries
    source_artifact: BenchPressThrowSourceArtifact
    acquisition: BenchPressThrowAcquisitionRecord
    support: BenchPressThrowMetricSupport

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.identity, BenchPressThrowMeasurementIdentity, "identity")
        _require_instance(self.series, BenchPressThrowVelocitySeries, "series")
        _require_verified_artifact(self.source_artifact)
        _require_instance(self.acquisition, BenchPressThrowAcquisitionRecord, "acquisition")
        _require_instance(self.support, BenchPressThrowMetricSupport, "support")
        if self.observation.identity != self.identity:
            raise ValueError("BPT evidence observation and identity do not agree")
        if self.identity.semantic.measurand != BPT_BAR_VELOCITY_MEASURAND:
            raise ValueError("BPT series identity has the wrong bar-velocity measurand")
        if self.identity.semantic.metric_definition != BPT_VELOCITY_SERIES_METRIC:
            raise ValueError("BPT series identity has the wrong velocity-series metric")
        if self.series.source_artifact_id != self.source_artifact.artifact_id:
            raise ValueError("BPT series artifact does not match evidence artifact")
        if self.series.acquisition_id != self.acquisition.acquisition_id:
            raise ValueError("BPT series acquisition does not match evidence acquisition")
        if self.series.source_measurement_identity_id != self.identity.identity_id:
            raise ValueError("BPT series identity does not match evidence identity")
        if self.source_artifact.content_digest != self.series.canonical_content_digest():
            raise ValueError("BPT source artifact digest does not match exact series")
        _validate_acquisition_binding(
            self.identity, self.source_artifact, self.acquisition, self.series
        )
        if self.observation.result.value != StructuredOutputReference(
            artifact_id=self.source_artifact.artifact_id,
            schema=BPT_VELOCITY_SERIES_SCHEMA,
        ):
            raise ValueError("BPT source observation must reference the exact velocity series")
        if self.observation.result.unit != METER_PER_SECOND:
            raise ValueError("BPT source observation must use m/s")
        if self.observation.result.classification.value_origin is not _origin_for_series(
            self.series.processing_state
        ):
            raise ValueError("BPT source origin does not match series processing state")
        if self.support.source_series_digest != self.series.canonical_content_digest():
            raise ValueError("BPT support is not bound to the exact series digest")
        if self.support.end_index >= len(self.series.samples):
            raise ValueError("BPT support end index is outside the exact series")
        if (
            self.support.start_time_s != self.series.samples[self.support.start_index][0]
            or self.support.end_time_s != self.series.samples[self.support.end_index][0]
        ):
            raise ValueError("BPT support times must equal exact sample timestamps")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("BPT source evidence observation must be valid")
        output_runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(output_runs) != 1 or output_runs[0].method != BPT_SOURCE_VELOCITY_SERIES_OPERATION:
            raise ValueError("BPT source evidence must preserve its registered processing run")

    @property
    def source_series_digest(self) -> str:
        return self.series.canonical_content_digest()


def create_bpt_velocity_series_evidence(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    identity: BenchPressThrowMeasurementIdentity,
    series: BenchPressThrowVelocitySeries,
    source_artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    support: BenchPressThrowMetricSupport,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> BenchPressThrowVelocitySeriesEvidence:
    """Create exact BPT series evidence; support is never a raw index pair."""

    _require_instance(context, ObservationContext, "context")
    _require_instance(identity, BenchPressThrowMeasurementIdentity, "identity")
    _require_instance(series, BenchPressThrowVelocitySeries, "series")
    _require_verified_artifact(source_artifact)
    _require_instance(acquisition, BenchPressThrowAcquisitionRecord, "acquisition")
    if observation_id.instance_type != "observation" or result_id.instance_type != "result":
        raise ValueError("BPT evidence requires observation and result identifiers")
    if identity.processing.registered_operation != BPT_SOURCE_VELOCITY_SERIES_OPERATION:
        raise ValueError("BPT series identity must use the registered source operation")
    if identity.version.processing_method != BPT_SOURCE_VELOCITY_SERIES_OPERATION:
        raise ValueError("BPT series version must use the registered source operation")
    _validate_acquisition_binding(identity, source_artifact, acquisition, series)
    if source_artifact.artifact_id != series.source_artifact_id:
        raise ValueError("BPT artifact does not match series")
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"bpt-source:{observation_id.value}"
        ),
        source_artifact_ids=(source_artifact.artifact_id,),
        method=BPT_SOURCE_VELOCITY_SERIES_OPERATION,
        parameters=identity.processing.method_parameters,
        software_version=identity.version.software_version,
        output_entity_id=observation_id,
    )
    provenance = Provenance(
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
                series.series_id.qualified,
                run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                support.support_id.qualified,
                run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                RES68_DECISION_EXPLOSIVE_TEST_FAMILY.stable_id,
                run.processing_run_id.qualified,
                LineageRelation.SUPPORTED_BY,
            ),
            LineageEdge(
                run.processing_run_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
        evidence_references=(
            EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),
            *evidence_references,
        ),
        recorded_at=recorded_at or context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=StructuredOutputReference(
                artifact_id=source_artifact.artifact_id,
                schema=BPT_VELOCITY_SERIES_SCHEMA,
            ),
            unit=METER_PER_SECOND,
            classification=ScientificClassification(
                _origin_for_series(series.processing_state), ()
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return BenchPressThrowVelocitySeriesEvidence(
        observation=observation,
        identity=identity,
        series=series,
        source_artifact=source_artifact,
        acquisition=acquisition,
        support=support,
    )


def build_bpt_provider_metric_observation(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    protocol_identity: BenchPressThrowProtocolIdentity,
    metric: RegistryReference,
    value: float,
    unit: UnitReference,
    source_artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    value_origin: ValueOrigin,
    provider_algorithm: RegistryReference | None = None,
    method_parameters: tuple[MetadataEntry, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Represent a provider scalar without relabelling it DynamisLM-derived."""

    if metric in {
        BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
        BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    }:
        raise ValueError("provider metric builder cannot mint a DynamisLM operation identity")
    if metric not in {
        BPT_PROVIDER_MEAN_VELOCITY_METRIC,
        BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
        BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
        BPT_PROVIDER_MEAN_POWER_METRIC,
        BPT_PROVIDER_PEAK_POWER_METRIC,
    }:
        raise ValueError("metric is not a registered BPT provider metric")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("provider BPT metric must remain source/provider-origin")
    _require_instance(protocol_identity, BenchPressThrowProtocolIdentity, "protocol_identity")
    _require_instance(context, ObservationContext, "context")
    _require_verified_artifact(source_artifact)
    _require_instance(acquisition, BenchPressThrowAcquisitionRecord, "acquisition")
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError("provider BPT metric value must be numeric")
    if unit not in {METER_PER_SECOND, WATT}:
        raise ValueError("provider BPT provider metric must use a registered unit")
    power_metrics = {BPT_PROVIDER_MEAN_POWER_METRIC, BPT_PROVIDER_PEAK_POWER_METRIC}
    if metric in power_metrics and unit != WATT:
        raise ValueError("BPT provider power must use watts")
    if metric not in power_metrics and unit != METER_PER_SECOND:
        raise ValueError("BPT provider velocity must use m/s")
    measurand = (
        BPT_BAR_VELOCITY_MEASURAND
        if unit == METER_PER_SECOND
        else BPT_MEAN_POWER_MEASURAND
        if metric == BPT_PROVIDER_MEAN_POWER_METRIC
        else BPT_PEAK_POWER_MEASURAND
    )
    parameters = (
        MetadataEntry("provider_metric", metric.stable_id),
        MetadataEntry("value_origin", value_origin.value),
        *method_parameters,
    )
    identity = BenchPressThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"bpt-provider:{metric.identifier.key}:{observation_id.value}",
            BPT_REGISTRY_VERSION,
        ),
        semantic=BenchPressThrowSemanticIdentity(
            construct=BPT_CONSTRUCT,
            test_family=BPT_TEST_FAMILY,
            protocol=protocol_identity.reference,
            measurand=measurand,
            metric_definition=metric,
            protocol_identity=protocol_identity,
        ),
        acquisition=BPTAcquisitionIdentity(
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
        processing=BenchPressThrowProcessingIdentity(
            registered_operation=BPT_PROVIDER_METRIC_SOURCE_OPERATION,
            method_parameters=parameters,
            processing_state=(
                BPTProcessingState.RAW_ACQUIRED
                if value_origin is ValueOrigin.SOURCE_REPORTED
                else BPTProcessingState.PROVIDER_PROCESSED
            ),
            provider_algorithm=provider_algorithm,
            timebase=acquisition.timebase,
        ),
        version=VersionIdentity(
            processing_method=BPT_PROVIDER_METRIC_SOURCE_OPERATION,
            method_registry_version=BPT_REGISTRY_VERSION,
            software_version=BPT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"bpt-provider:{observation_id.value}"
        ),
        source_artifact_ids=(source_artifact.artifact_id,),
        method=BPT_PROVIDER_METRIC_SOURCE_OPERATION,
        parameters=parameters,
        software_version=BPT_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = Provenance(
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
                run.processing_run_id.qualified, observation_id.qualified, LineageRelation.PRODUCED
            ),
        ),
        evidence_references=(EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),),
        recorded_at=recorded_at or context.observed_at,
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=ScalarValue(float(value)),
            unit=unit,
            classification=ScientificClassification(value_origin, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BPTSourceQualificationEvidence:
    """Source/provider qualification bound to one exact BPT observation."""

    target_observation_id: InstanceIdentifier
    qualification_observation: ScientificMeasurementObservation
    qualification_reference: RegistryReference

    def __post_init__(self) -> None:
        if self.target_observation_id.instance_type != "observation":
            raise ValueError("BPT target observation ID must identify an observation")
        _require_instance(
            self.qualification_observation,
            ScientificMeasurementObservation,
            "qualification_observation",
        )
        if self.qualification_reference != BPT_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("BPT qualification reference is not registered")
        value = self.qualification_observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("BPT qualification must be categorical")
        try:
            BPTQualificationStatus(value.category)
        except ValueError as exc:
            raise ValueError("BPT qualification category is not registered") from exc
        if self.qualification_observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("BPT qualification must remain source/provider-origin")
        if self.qualification_observation.result.status is not ResultStatus.VALID:
            raise ValueError("BPT qualification observation must be valid")
        if any(
            not isinstance(artifact, BenchPressThrowSourceArtifact)
            or not artifact.immutable
            or artifact.status is not BPTArtifactStatus.VERIFIED
            for artifact in self.qualification_observation.provenance.source_artifacts
        ):
            raise ValueError("BPT qualification must preserve verified source artifacts")
        identity = self.qualification_observation.identity
        if not isinstance(identity, BenchPressThrowMeasurementIdentity):
            raise ValueError("BPT qualification requires BPT identity")
        if (
            identity.semantic.measurand != BPT_QUALIFICATION_MEASURAND
            or identity.semantic.metric_definition != BPT_QUALIFICATION_METRIC
        ):
            raise ValueError("BPT qualification identity has the wrong measurand/metric")
        if identity.processing.registered_operation != BPT_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("BPT qualification identity has the wrong operation")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if parameters.get("target_observation_id") != self.target_observation_id.qualified:
            raise ValueError("BPT qualification target is not preserved")
        if parameters.get("source_status") != self.status.value:
            raise ValueError("BPT qualification status is not preserved")

    @property
    def status(self) -> BPTQualificationStatus:
        value = self.qualification_observation.result.value
        assert isinstance(value, CategoricalValue)
        return BPTQualificationStatus(value.category)


def build_bpt_qualification_source_observation(
    *,
    target_observation: ScientificMeasurementObservation,
    reported_status: BPTQualificationStatus,
    source_artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    output_observation_id: InstanceIdentifier | None = None,
    reason_codes: tuple[str, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Ingest upstream BPT qualification; normalization remains separate."""

    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    _require_instance(reported_status, BPTQualificationStatus, "reported_status")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError("BPT qualification source origin is invalid")
    _require_verified_artifact(source_artifact)
    _require_instance(acquisition, BenchPressThrowAcquisitionRecord, "acquisition")
    target_identity = target_observation.identity
    if not isinstance(target_identity, BenchPressThrowMeasurementIdentity):
        raise ValueError("BPT target requires BPT identity")
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"bpt-qualification:{target_observation.observation_id.value}"
    )
    parameters = (
        MetadataEntry("target_observation_id", target_observation.observation_id.qualified),
        MetadataEntry("source_status", reported_status.value),
        MetadataEntry("reason_codes", canonical_json(reason_codes)),
    )
    identity = BenchPressThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"bpt-qualification:{observation_id.value}",
            BPT_REGISTRY_VERSION,
        ),
        semantic=BenchPressThrowSemanticIdentity(
            construct=target_identity.semantic.construct,
            test_family=BPT_TEST_FAMILY,
            protocol=target_identity.semantic.protocol,
            measurand=BPT_QUALIFICATION_MEASURAND,
            metric_definition=BPT_QUALIFICATION_METRIC,
            protocol_identity=target_identity.semantic.protocol_identity,
        ),
        acquisition=BPTAcquisitionIdentity(
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
        processing=BenchPressThrowProcessingIdentity(
            registered_operation=BPT_SOURCE_QUALIFICATION_OPERATION,
            method_parameters=parameters,
            processing_state=(
                BPTProcessingState.RAW_ACQUIRED
                if value_origin is ValueOrigin.SOURCE_REPORTED
                else BPTProcessingState.PROVIDER_PROCESSED
            ),
            timebase=acquisition.timebase,
        ),
        version=VersionIdentity(
            processing_method=BPT_SOURCE_QUALIFICATION_OPERATION,
            method_registry_version=BPT_REGISTRY_VERSION,
            software_version=BPT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"bpt-qualification:{observation_id.value}"),
        value=CategoricalValue(reported_status.value),
        unit=None,
        classification=ScientificClassification(value_origin, ()),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    return _build_simple_source_observation(
        observation_id=observation_id,
        context=target_observation.context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )


def _build_simple_source_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: BenchPressThrowMeasurementIdentity,
    result: MeasurementResult,
    source_artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    recorded_at: datetime_module.datetime | None,
) -> ScientificMeasurementObservation:
    _validate_acquisition_binding(identity, source_artifact, acquisition)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"bpt-source:{observation_id.value}"
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


def normalize_bpt_qualification(
    source_observation: ScientificMeasurementObservation,
    target_observation: ScientificMeasurementObservation,
) -> BPTSourceQualificationEvidence:
    _require_instance(source_observation, ScientificMeasurementObservation, "source_observation")
    _require_instance(target_observation, ScientificMeasurementObservation, "target_observation")
    if source_observation.context != target_observation.context:
        raise ValueError("BPT qualification context does not match target")
    source_identity = source_observation.identity
    target_identity = target_observation.identity
    if not isinstance(source_identity, BenchPressThrowMeasurementIdentity) or not isinstance(
        target_identity, BenchPressThrowMeasurementIdentity
    ):
        raise ValueError("BPT qualification and target require BPT identities")
    if (
        source_identity.semantic.construct != target_identity.semantic.construct
        or source_identity.semantic.test_family != BPT_TEST_FAMILY
        or target_identity.semantic.test_family != BPT_TEST_FAMILY
        or source_identity.semantic.protocol != target_identity.semantic.protocol
        or source_identity.semantic.protocol_identity != target_identity.semantic.protocol_identity
    ):
        raise ValueError("BPT qualification source is bound to a different protocol")
    target_artifacts = {
        item.artifact_id: item for item in target_observation.provenance.source_artifacts
    }
    source_artifacts = {
        item.artifact_id: item for item in source_observation.provenance.source_artifacts
    }
    if not source_artifacts or not set(source_artifacts).issubset(target_artifacts):
        raise ValueError("BPT qualification artifacts are not bound to target")
    if any(target_artifacts[key] != value for key, value in source_artifacts.items()):
        raise ValueError("BPT qualification artifact content was tampered")
    target_acquisitions = {
        item.acquisition_id: item for item in target_observation.provenance.acquisitions
    }
    source_acquisitions = {
        item.acquisition_id: item for item in source_observation.provenance.acquisitions
    }
    if not source_acquisitions or not set(source_acquisitions).issubset(target_acquisitions):
        raise ValueError("BPT qualification acquisitions are not bound to target")
    if any(target_acquisitions[key] != value for key, value in source_acquisitions.items()):
        raise ValueError("BPT qualification acquisition content was tampered")
    evidence = BPTSourceQualificationEvidence(
        target_observation_id=target_observation.observation_id,
        qualification_observation=source_observation,
        qualification_reference=BPT_SOURCE_QUALIFICATION_OPERATION,
    )
    if evidence.status is BPTQualificationStatus.UNKNOWN:
        raise ValueError("BPT source qualification must report QUALIFIED or REJECTED")
    return evidence


def require_qualified_bpt(
    evidence: BPTSourceQualificationEvidence,
    target_observation: ScientificMeasurementObservation,
) -> None:
    if not isinstance(evidence, BPTSourceQualificationEvidence):
        raise ValueError("typed BPT source qualification evidence is required")
    normalized = normalize_bpt_qualification(evidence.qualification_observation, target_observation)
    if normalized != evidence:
        raise ValueError("BPT qualification evidence was rebound or tampered")
    if evidence.status is not BPTQualificationStatus.QUALIFIED:
        raise ValueError("BPT source observation is not qualified")


__all__ = [
    "BPTSourceQualificationEvidence",
    "BenchPressThrowVelocitySeriesEvidence",
    "build_bpt_provider_metric_observation",
    "build_bpt_qualification_source_observation",
    "create_bpt_velocity_series_evidence",
    "normalize_bpt_qualification",
    "require_qualified_bpt",
]
