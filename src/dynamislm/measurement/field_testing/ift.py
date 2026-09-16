"""Exact canonical 30-15 IFT protocol, stage evidence and VIFT authority."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.field_testing._common import (
    FieldTestingSourceQualificationEvidence,
    _build_derived_observation,
    _finite,
    _numeric_scalar,
    _protocol_processing_components,
    _refusal,
    _require_field_testing_source_lineage,
    _require_qualified,
    _require_verified_field_artifact,
    _source_processing_state,
    build_field_testing_source_observation,
    normalize_field_test_qualification,
)
from dynamislm.measurement.field_testing.identity import (
    FieldTestFamily,
    FieldTestingAcquisitionIdentity,
    FieldTestingAcquisitionRecord,
    FieldTestingProcessingIdentity,
    FieldTestingProtocolAttribute,
    FieldTestingProtocolIdentity,
    FieldTestingSemanticIdentity,
    FieldTestingSourceArtifact,
    FieldTestProcessingState,
    FieldTestQualificationStatus,
    FieldTestSensorModality,
    IFT30_15MeasurementIdentity,
    ReactionTimeSemantics,
    StartInitiationMode,
    TimingGateTopology,
)
from dynamislm.measurement.field_testing.registry import (
    FIELD_TESTING_REGISTRY_VERSION,
    FIELD_TESTING_SOFTWARE_VERSION,
    IFT30_15_AUDIO_PACE,
    IFT30_15_CONSTRUCT,
    IFT30_15_PROTOCOL_V1,
    IFT30_15_TERMINATION_RULE,
    IFT30_15_TEST_FAMILY,
    IFT_AUDIO_SIGNAL_TRIGGER,
    IFT_STAGE_COMPLETION_MEASURAND,
    IFT_STAGE_COMPLETION_METRIC,
    IFT_STAGE_COMPLETION_SOURCE_OPERATION,
    IFT_STAGE_SOURCE_OPERATION,
    IFT_STAGE_VELOCITY_MEASURAND,
    IFT_STAGE_VELOCITY_METRIC,
    IFT_TERMINATION_MEASURAND,
    IFT_TERMINATION_METRIC,
    IFT_TEST_SOURCE_OPERATION,
    KILOMETER_PER_HOUR,
    METER,
    VIFT_ESTIMATOR,
    VIFT_MEASURAND,
    VIFT_METRIC,
    VIFT_OPERATION,
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
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    CategoricalValue,
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import ProcessingRun
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult
from dynamislm.serialization import register_serializable_type


class IFTRecoveryMode(StrEnum):
    WALKING_PASSIVE_LINE_REPOSITIONING = "WALKING_PASSIVE_LINE_REPOSITIONING"
    PASSIVE = "PASSIVE"
    UNKNOWN = "UNKNOWN"


class IFTStageCompletion(StrEnum):
    COMPLETED = "COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"
    UNKNOWN = "UNKNOWN"


class IFTTerminationReason(StrEnum):
    VOLUNTARY_EXHAUSTION = "VOLUNTARY_EXHAUSTION"
    THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES = "THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class IFT30_15ProtocolIdentity(FieldTestingProtocolIdentity):  # noqa: N801
    """Exact 40 m canonical 30-15 IFT protocol identity."""

    course_length_m: float
    run_interval_s: float
    recovery_interval_s: float
    recovery_mode: IFTRecoveryMode
    initial_velocity_kmh: float
    stage_increment_kmh: float
    control_zone_m: float
    pace_reference: RegistryReference
    termination_rule: RegistryReference

    def __post_init__(self) -> None:
        FieldTestingProtocolIdentity.__post_init__(self)
        if self.family is not FieldTestFamily.INTERMITTENT_FITNESS_30_15:
            raise ValueError("IFT30_15ProtocolIdentity requires the 30-15 IFT family")
        _require_enum(self.recovery_mode, IFTRecoveryMode, "recovery_mode")
        for name in (
            "course_length_m",
            "run_interval_s",
            "recovery_interval_s",
            "initial_velocity_kmh",
            "stage_increment_kmh",
            "control_zone_m",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        _require_instance(self.pace_reference, RegistryReference, "pace_reference")
        _require_instance(self.termination_rule, RegistryReference, "termination_rule")
        if self.reference == IFT30_15_PROTOCOL_V1:
            expected: dict[str, object] = {
                "course_length_m": 40.0,
                "run_interval_s": 30.0,
                "recovery_interval_s": 15.0,
                "recovery_mode": IFTRecoveryMode.WALKING_PASSIVE_LINE_REPOSITIONING,
                "initial_velocity_kmh": 8.0,
                "stage_increment_kmh": 0.5,
                "control_zone_m": 3.0,
                "pace_reference": IFT30_15_AUDIO_PACE,
                "termination_rule": IFT30_15_TERMINATION_RULE,
                "start_position": "protocol-defined starting line",
                "start_initiation_mode": StartInitiationMode.AUDIO_OR_GUN_TRIGGER,
                "reaction_time_semantics": ReactionTimeSemantics.NOT_APPLICABLE,
                "sensor_modality": FieldTestSensorModality.SOURCE_REPORTED,
                "start_trigger": IFT_AUDIO_SIGNAL_TRIGGER,
                "finish_trigger": IFT_AUDIO_SIGNAL_TRIGGER,
            }
            for name, expected_value in expected.items():
                if getattr(self, name) != expected_value:
                    raise ValueError(f"canonical 30-15 IFT protocol has a different {name}")

    def stage_velocity_kmh(self, stage_index: int) -> float:
        if type(stage_index) is not int or stage_index < 1:
            raise ValueError("stage_index must be a positive integer")
        return self.initial_velocity_kmh + self.stage_increment_kmh * (stage_index - 1)


def ift30_15_protocol_v1() -> IFT30_15ProtocolIdentity:
    """Return the canonical 40 m 30-15 IFT protocol."""

    return IFT30_15ProtocolIdentity(
        family=FieldTestFamily.INTERMITTENT_FITNESS_30_15,
        protocol_version=FIELD_TESTING_REGISTRY_VERSION,
        reference=IFT30_15_PROTOCOL_V1,
        course_layout=(
            FieldTestingProtocolAttribute("course_length_m", 40.0, METER),
            FieldTestingProtocolAttribute("control_zone_m", 3.0, METER),
            FieldTestingProtocolAttribute("run_interval_s", 30.0),
            FieldTestingProtocolAttribute("recovery_interval_s", 15.0),
        ),
        start_position="protocol-defined starting line",
        start_initiation_mode=StartInitiationMode.AUDIO_OR_GUN_TRIGGER,
        reaction_time_semantics=ReactionTimeSemantics.NOT_APPLICABLE,
        start_trigger=IFT_AUDIO_SIGNAL_TRIGGER,
        finish_trigger=IFT_AUDIO_SIGNAL_TRIGGER,
        sensor_modality=FieldTestSensorModality.SOURCE_REPORTED,
        gate_topology=TimingGateTopology.UNKNOWN,
        recovery_mode=IFTRecoveryMode.WALKING_PASSIVE_LINE_REPOSITIONING,
        course_length_m=40.0,
        run_interval_s=30.0,
        recovery_interval_s=15.0,
        initial_velocity_kmh=8.0,
        stage_increment_kmh=0.5,
        control_zone_m=3.0,
        pace_reference=IFT30_15_AUDIO_PACE,
        termination_rule=IFT30_15_TERMINATION_RULE,
    )


def _ift_stage_parameters(
    protocol: IFT30_15ProtocolIdentity,
    stage_index: int,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("stage_index", stage_index),
        MetadataEntry("target_stage_velocity_kmh", protocol.stage_velocity_kmh(stage_index)),
        MetadataEntry("course_length_m", protocol.course_length_m),
        MetadataEntry("run_interval_s", protocol.run_interval_s),
        MetadataEntry("recovery_interval_s", protocol.recovery_interval_s),
    )


def _acquisition_identity(
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
) -> FieldTestingAcquisitionIdentity:
    return FieldTestingAcquisitionIdentity(
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
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IFTStageCompletionEvidence:
    """Typed source/provider adjudication for one exact IFT stage."""

    observation: ScientificMeasurementObservation
    target_stage_observation_id: InstanceIdentifier

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_field_testing_source_lineage(self.observation)
        _require_instance(
            self.target_stage_observation_id,
            InstanceIdentifier,
            "target_stage_observation_id",
        )
        if self.target_stage_observation_id.instance_type != "observation":
            raise ValueError("target_stage_observation_id must identify an observation")
        identity = self.observation.identity
        if not isinstance(identity, IFT30_15MeasurementIdentity):
            raise ValueError("IFT completion requires IFT30_15MeasurementIdentity")
        protocol = identity.semantic.protocol_identity
        if not isinstance(protocol, IFT30_15ProtocolIdentity):
            raise ValueError("IFT completion requires IFT30_15ProtocolIdentity")
        if identity.semantic.metric_definition != IFT_STAGE_COMPLETION_METRIC:
            raise ValueError("IFT completion has the wrong metric")
        if identity.semantic.measurand != IFT_STAGE_COMPLETION_MEASURAND:
            raise ValueError("IFT completion has the wrong measurand")
        if identity.processing.registered_operation != IFT_STAGE_COMPLETION_SOURCE_OPERATION:
            raise ValueError("IFT completion uses an unregistered source operation")
        value = self.observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("IFT completion must carry a categorical source result")
        try:
            IFTStageCompletion(value.category)
        except ValueError as exc:
            raise ValueError("completion category is not registered") from exc
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("IFT completion must remain source-reported or provider-derived")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("IFT completion must be valid")
        for artifact in self.observation.provenance.source_artifacts:
            if not isinstance(artifact, FieldTestingSourceArtifact):
                raise ValueError("IFT completion must preserve field-test artifacts")
            _require_verified_field_artifact(artifact)
        if any(
            not isinstance(acquisition, FieldTestingAcquisitionRecord)
            for acquisition in self.observation.provenance.acquisitions
        ):
            raise ValueError("IFT completion must preserve typed acquisitions")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            parameters.get("target_stage_observation_id")
            != self.target_stage_observation_id.qualified
        ):
            raise ValueError("IFT completion target is not preserved in source identity")
        if parameters.get("stage_index") != self.stage_index:
            raise ValueError("IFT completion stage index is not preserved in source identity")
        if parameters.get("target_stage_velocity_kmh") != self.target_stage_velocity_kmh:
            raise ValueError("IFT completion target velocity is not preserved in source identity")
        if parameters.get("completion") != self.completion.value:
            raise ValueError("IFT completion category is not preserved in source identity")
        if self.miss_count is not None and parameters.get("miss_count") != self.miss_count:
            raise ValueError("IFT completion checkpoint count is not preserved in source identity")
        expected_state = (
            FieldTestProcessingState.PROVIDER_PROCESSED
            if self.observation.result.classification.value_origin is ValueOrigin.PROVIDER_DERIVED
            else FieldTestProcessingState.RAW_ACQUIRED
        )
        if identity.processing.processing_state is not expected_state:
            raise ValueError("IFT completion processing state does not match source origin")

    @property
    def protocol(self) -> IFT30_15ProtocolIdentity:
        identity = self.observation.identity
        assert isinstance(identity, IFT30_15MeasurementIdentity)
        protocol = identity.semantic.protocol_identity
        assert isinstance(protocol, IFT30_15ProtocolIdentity)
        return protocol

    @property
    def _parameters(self) -> dict[str, object]:
        return {
            entry.key: entry.value
            for entry in self.observation.identity.processing.method_parameters
        }

    @property
    def stage_index(self) -> int:
        value = self._parameters.get("stage_index")
        if type(value) is not int or value < 1:
            raise ValueError("IFT completion stage index must be a positive integer")
        return value

    @property
    def target_stage_velocity_kmh(self) -> float:
        return _finite(
            self._parameters.get("target_stage_velocity_kmh"),
            "target_stage_velocity_kmh",
        )

    @property
    def completion(self) -> IFTStageCompletion:
        value = self.observation.result.value
        assert isinstance(value, CategoricalValue)
        return IFTStageCompletion(value.category)

    @property
    def miss_count(self) -> int | None:
        value = self._parameters.get("miss_count")
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise ValueError("IFT completion miss_count must be a non-negative integer")
        return value


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IFTStageEvidence:
    """One stage source observation bound to source completion evidence."""

    observation: ScientificMeasurementObservation
    completion_evidence: IFTStageCompletionEvidence
    source_qualification: FieldTestingSourceQualificationEvidence | None = None

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_field_testing_source_lineage(self.observation)
        _require_instance(
            self.completion_evidence,
            IFTStageCompletionEvidence,
            "completion_evidence",
        )
        identity = self.observation.identity
        if not isinstance(identity, IFT30_15MeasurementIdentity):
            raise ValueError("IFT stage requires IFT30_15MeasurementIdentity")
        protocol = identity.semantic.protocol_identity
        if not isinstance(protocol, IFT30_15ProtocolIdentity):
            raise ValueError("IFT stage requires IFT30_15ProtocolIdentity")
        if identity.semantic.metric_definition != IFT_STAGE_VELOCITY_METRIC:
            raise ValueError("IFT stage has the wrong metric")
        if identity.processing.registered_operation != IFT_STAGE_SOURCE_OPERATION:
            raise ValueError("IFT source stage uses an unregistered operation")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("IFT source stage cannot be a model estimate")
        if self.observation.result.unit != KILOMETER_PER_HOUR:
            raise ValueError("IFT stage velocity must use km/h")
        if self.completion_evidence.target_stage_observation_id != self.observation.observation_id:
            raise ValueError("IFT completion targets a different stage observation")
        if self.completion_evidence.observation.context != self.observation.context:
            raise ValueError("IFT completion context does not match the stage observation")
        if self.completion_evidence.protocol != protocol:
            raise ValueError("IFT completion and stage use different protocols")
        if _numeric_scalar(self.observation) != self.target_stage_velocity_kmh:
            raise ValueError("IFT stage target velocity does not match source result")
        if protocol.reference == IFT30_15_PROTOCOL_V1:
            if self.target_stage_velocity_kmh != protocol.stage_velocity_kmh(self.stage_index):
                raise ValueError("IFT stage velocity does not reproduce from canonical protocol")
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            params.get("stage_index") != self.stage_index
            or params.get("target_stage_velocity_kmh") != self.target_stage_velocity_kmh
        ):
            raise ValueError("IFT stage index/velocity is not preserved in processing identity")
        if self.source_qualification is not None:
            _require_qualified(self.source_qualification, self.observation)

    @property
    def protocol(self) -> IFT30_15ProtocolIdentity:
        return self.completion_evidence.protocol

    @property
    def stage_index(self) -> int:
        return self.completion_evidence.stage_index

    @property
    def target_stage_velocity_kmh(self) -> float:
        return self.completion_evidence.target_stage_velocity_kmh

    @property
    def completion(self) -> IFTStageCompletion:
        return self.completion_evidence.completion

    @property
    def miss_count(self) -> int | None:
        return self.completion_evidence.miss_count

    @property
    def is_completed(self) -> bool:
        return self.completion is IFTStageCompletion.COMPLETED

    @property
    def is_source_qualified(self) -> bool:
        return (
            self.source_qualification is not None
            and self.source_qualification.status is FieldTestQualificationStatus.QUALIFIED
        )


def _ift_source_key(observation: ScientificMeasurementObservation) -> object:
    identity = observation.identity
    if not isinstance(identity, IFT30_15MeasurementIdentity):
        raise ValueError("IFT source must use IFT30_15MeasurementIdentity")
    acquisition = identity.acquisition
    processing = identity.processing
    return (
        acquisition.device,
        acquisition.provider,
        acquisition.sensor_modality,
        acquisition.sampling,
        acquisition.axis_or_frame,
        acquisition.sensor_channel,
        processing.event_definitions,
        processing.filtering,
        processing.filtering_status,
        processing.smoothing,
        processing.interpolation,
        processing.processing_state,
        observation.result.classification.value_origin,
        identity.version.software_version,
        identity.version.hardware_firmware,
    )


def build_ift_stage_source_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    protocol: IFT30_15ProtocolIdentity,
    stage_index: int,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    processing_run: ProcessingRun | None = None,
) -> ScientificMeasurementObservation:
    """Ingest one canonical IFT stage target-velocity observation."""

    if not isinstance(protocol, IFT30_15ProtocolIdentity):
        raise ValueError("protocol must be an IFT30_15ProtocolIdentity")
    if protocol.reference is None:
        raise ValueError("IFT stage requires a registered protocol")
    if type(stage_index) is not int or stage_index < 1:
        raise ValueError("stage_index must be a positive integer")
    _require_enum(value_origin, ValueOrigin, "value_origin")
    if value_origin in {ValueOrigin.DYNAMISLM_DERIVED, ValueOrigin.MODEL_ESTIMATE}:
        raise ValueError("IFT stage source cannot be DynamisLM-derived or estimated")
    target = protocol.stage_velocity_kmh(stage_index)
    parameters = _ift_stage_parameters(protocol, stage_index)
    identity = IFT30_15MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"ift30-15-stage:{observation_id.value}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=IFT30_15_CONSTRUCT,
            test_family=IFT30_15_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=IFT_STAGE_VELOCITY_MEASURAND,
            metric_definition=IFT_STAGE_VELOCITY_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=_acquisition_identity(source_artifact, acquisition),
        processing=FieldTestingProcessingIdentity(
            registered_operation=IFT_STAGE_SOURCE_OPERATION,
            method_parameters=parameters,
            unit=KILOMETER_PER_HOUR,
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
            processing_state=_source_processing_state(value_origin),
        ),
        version=VersionIdentity(
            processing_method=IFT_STAGE_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:ift-stage"),
        value=ScalarValue(target),
        unit=KILOMETER_PER_HOUR,
        classification=ScientificClassification(
            value_origin, (ScientificRole.PERFORMANCE_OUTCOME,)
        ),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    return build_field_testing_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        processing_run=processing_run,
    )


def build_ift_stage_completion_source_observation(
    *,
    stage_observation: ScientificMeasurementObservation,
    reported_completion: IFTStageCompletion,
    reported_miss_count: int | None = None,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> IFTStageCompletionEvidence:
    """Ingest source/provider stage completion and optional checkpoint data."""

    if not isinstance(stage_observation, ScientificMeasurementObservation):
        raise ValueError("stage_observation must be a scientific observation")
    stage_identity = stage_observation.identity
    if not isinstance(stage_identity, IFT30_15MeasurementIdentity):
        raise ValueError("stage_observation must use IFT30_15MeasurementIdentity")
    protocol = stage_identity.semantic.protocol_identity
    if not isinstance(protocol, IFT30_15ProtocolIdentity):
        raise ValueError("stage_observation must use IFT30_15ProtocolIdentity")
    if stage_identity.semantic.metric_definition != IFT_STAGE_VELOCITY_METRIC:
        raise ValueError("stage_observation must be an IFT stage velocity observation")
    _require_enum(reported_completion, IFTStageCompletion, "reported_completion")
    _require_enum(value_origin, ValueOrigin, "value_origin")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError(
            "IFT completion ingestion requires source-reported or provider-derived data"
        )
    if reported_miss_count is not None and (
        type(reported_miss_count) is not int or reported_miss_count < 0
    ):
        raise ValueError("reported_miss_count must be a non-negative integer")
    stage_parameters = _stage_parameters(stage_observation)
    stage_index_value = stage_parameters.get("stage_index")
    target_velocity_value = stage_parameters.get("target_stage_velocity_kmh")
    if type(stage_index_value) is not int or stage_index_value < 1:
        raise ValueError("stage source does not preserve a positive stage index")
    if isinstance(target_velocity_value, bool) or not isinstance(
        target_velocity_value, int | float
    ):
        raise ValueError("stage source does not preserve a numeric target velocity")
    parameters = [
        MetadataEntry("target_stage_observation_id", stage_observation.observation_id.qualified),
        MetadataEntry("stage_index", stage_index_value),
        MetadataEntry("target_stage_velocity_kmh", float(target_velocity_value)),
        MetadataEntry("completion", reported_completion.value),
    ]
    if reported_miss_count is not None:
        parameters.append(MetadataEntry("miss_count", reported_miss_count))
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"ift30-15-stage-completion:{stage_observation.observation_id.value}"
    )
    identity = IFT30_15MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"ift30-15-stage-completion:{observation_id.value}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=IFT30_15_CONSTRUCT,
            test_family=IFT30_15_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=IFT_STAGE_COMPLETION_MEASURAND,
            metric_definition=IFT_STAGE_COMPLETION_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=_acquisition_identity(source_artifact, acquisition),
        processing=FieldTestingProcessingIdentity(
            registered_operation=IFT_STAGE_COMPLETION_SOURCE_OPERATION,
            method_parameters=tuple(parameters),
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
            processing_state=_source_processing_state(value_origin),
        ),
        version=VersionIdentity(
            processing_method=IFT_STAGE_COMPLETION_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:completion"),
        value=CategoricalValue(reported_completion.value),
        unit=None,
        classification=ScientificClassification(value_origin, ()),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    observation = build_field_testing_source_observation(
        observation_id=observation_id,
        context=stage_observation.context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        recorded_at=recorded_at,
    )
    return IFTStageCompletionEvidence(observation, stage_observation.observation_id)


def _stage_parameters(observation: ScientificMeasurementObservation) -> dict[str, object]:
    identity = observation.identity
    if not isinstance(identity, IFT30_15MeasurementIdentity):
        raise ValueError("IFT stage must use IFT30_15MeasurementIdentity")
    return {entry.key: entry.value for entry in identity.processing.method_parameters}


def build_ift_stage_evidence(
    *,
    stage_observation: ScientificMeasurementObservation,
    completion_evidence: IFTStageCompletionEvidence,
    source_qualification_observation: ScientificMeasurementObservation | None = None,
) -> IFTStageEvidence:
    """Normalize one stage observation against pre-existing source completion evidence."""

    qualification = None
    if source_qualification_observation is not None:
        qualification = normalize_field_test_qualification(
            source_qualification_observation,
            stage_observation,
        )
    return IFTStageEvidence(stage_observation, completion_evidence, qualification)


def qualify_ift_stage(
    stage: IFTStageEvidence,
    *,
    source_observation: ScientificMeasurementObservation,
) -> IFTStageEvidence:
    if not isinstance(stage, IFTStageEvidence):
        raise ValueError("stage must be an IFTStageEvidence")
    qualification = normalize_field_test_qualification(
        source_observation,
        stage.observation,
    )
    return IFTStageEvidence(
        stage.observation,
        stage.completion_evidence,
        qualification,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IFTTerminationEvidence:
    """Source/provider termination reason bound to a categorical observation."""

    observation: ScientificMeasurementObservation

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_field_testing_source_lineage(self.observation)
        value = self.observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("termination evidence must carry a categorical source result")
        try:
            IFTTerminationReason(value.category)
        except ValueError as exc:
            raise ValueError("termination category is not registered") from exc
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("termination evidence must remain source-reported or provider-derived")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("termination evidence must be valid")
        for artifact in self.observation.provenance.source_artifacts:
            if not isinstance(artifact, FieldTestingSourceArtifact):
                raise ValueError("termination evidence must preserve field-test artifacts")
            _require_verified_field_artifact(artifact)
        if any(
            not isinstance(acquisition, FieldTestingAcquisitionRecord)
            for acquisition in self.observation.provenance.acquisitions
        ):
            raise ValueError("termination evidence must preserve typed acquisitions")
        identity = self.observation.identity
        if not isinstance(identity, IFT30_15MeasurementIdentity):
            raise ValueError("termination evidence requires IFT30_15MeasurementIdentity")
        if identity.semantic.metric_definition != IFT_TERMINATION_METRIC:
            raise ValueError("termination evidence has the wrong metric")
        if identity.semantic.measurand != IFT_TERMINATION_MEASURAND:
            raise ValueError("termination evidence has the wrong measurand")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if identity.processing.registered_operation != IFT_TEST_SOURCE_OPERATION:
            raise ValueError("termination evidence uses an unregistered source operation")
        if self.reason is IFTTerminationReason.UNKNOWN:
            raise ValueError("termination evidence must report an explicit reason")
        if parameters.get("termination_reason") != self.reason.value:
            raise ValueError("termination reason is not preserved in source identity")

    @property
    def reason(self) -> IFTTerminationReason:
        value = self.observation.result.value
        assert isinstance(value, CategoricalValue)
        return IFTTerminationReason(value.category)

    @property
    def target_stage_observation_id(self) -> InstanceIdentifier:
        identity = self.observation.identity
        assert isinstance(identity, IFT30_15MeasurementIdentity)
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        value = parameters.get("target_stage_observation_id")
        if not isinstance(value, str):
            raise ValueError("termination evidence target stage is unresolved")
        instance_type, _, instance_value = value.partition(":")
        if instance_type != "observation" or not instance_value:
            raise ValueError("termination evidence target stage is invalid")
        return InstanceIdentifier(instance_type, instance_value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IFTTestEvidence:
    """Complete source-qualified stage/test evidence for VIFT."""

    test_id: InstanceIdentifier
    protocol: IFT30_15ProtocolIdentity
    stages: tuple[IFTStageEvidence, ...]
    termination: IFTTerminationEvidence

    def __post_init__(self) -> None:
        _require_instance(self.test_id, InstanceIdentifier, "test_id")
        if self.test_id.instance_type != "ift-test":
            raise ValueError("test_id must identify an IFT test")
        _require_instance(self.protocol, IFT30_15ProtocolIdentity, "protocol")
        _require_tuple_items(self.stages, IFTStageEvidence, "stages")
        if not self.stages:
            raise ValueError("IFT test requires at least one stage")
        _require_instance(self.termination, IFTTerminationEvidence, "termination")
        if any(stage.protocol != self.protocol for stage in self.stages):
            raise ValueError("IFT stages must use one exact protocol")
        if len({stage.stage_index for stage in self.stages}) != len(self.stages):
            raise ValueError("IFT stages must have unique indices")
        ordered = tuple(sorted(self.stages, key=lambda stage: stage.stage_index))
        if tuple(stage.stage_index for stage in ordered) != tuple(range(1, len(ordered) + 1)):
            raise ValueError("IFT stages must contain a complete ordered prefix")
        if any(not stage.is_source_qualified for stage in ordered):
            raise ValueError("every IFT stage must be source-qualified")
        first_context = ordered[0].observation.context
        for stage in ordered[1:]:
            context = stage.observation.context
            if (
                context.athlete_id != first_context.athlete_id
                or context.session_id != first_context.session_id
                or context.test_instance_id != first_context.test_instance_id
                or context.trial_id != first_context.trial_id
                or context.observed_at != first_context.observed_at
                or context.population_context != first_context.population_context
                or context.environment != first_context.environment
                or context.context_metadata != first_context.context_metadata
            ):
                raise ValueError("IFT stages must share one athlete/session/test scope")
            if _ift_source_key(stage.observation) != _ift_source_key(ordered[0].observation):
                raise ValueError("IFT stages must share source-device processing identity")
        termination_context = self.termination.observation.context
        if (
            termination_context.athlete_id != first_context.athlete_id
            or termination_context.session_id != first_context.session_id
            or termination_context.test_instance_id != first_context.test_instance_id
            or termination_context.trial_id != first_context.trial_id
            or termination_context.observed_at != first_context.observed_at
            or termination_context.population_context != first_context.population_context
            or termination_context.environment != first_context.environment
            or termination_context.context_metadata != first_context.context_metadata
        ):
            raise ValueError("termination evidence is bound to a different IFT test")
        if _ift_source_key(self.termination.observation) != _ift_source_key(ordered[0].observation):
            raise ValueError("termination evidence must use the same source-device identity")
        last = ordered[-1]
        if self.termination.target_stage_observation_id != last.observation.observation_id:
            raise ValueError("termination evidence is bound to a different final stage")

    @property
    def final_completed_stage(self) -> IFTStageEvidence:
        completed = tuple(stage for stage in self.stages if stage.is_completed)
        if not completed:
            raise ValueError("IFT test has no successfully completed stage")
        return max(completed, key=lambda stage: stage.stage_index)

    @property
    def source_observations(self) -> tuple[ScientificMeasurementObservation, ...]:
        observations: list[ScientificMeasurementObservation] = []
        for stage in self.stages:
            assert stage.source_qualification is not None
            observations.extend(
                (
                    stage.observation,
                    stage.completion_evidence.observation,
                    stage.source_qualification.qualification_observation,
                )
            )
        observations.append(self.termination.observation)
        return tuple(observations)


def build_ift_termination_source_observation(
    *,
    target_stage: IFTStageEvidence,
    reported_reason: IFTTerminationReason,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    output_observation_id: InstanceIdentifier | None = None,
) -> ScientificMeasurementObservation:
    """Ingest an explicit source/provider termination reason."""

    if not isinstance(target_stage, IFTStageEvidence):
        raise ValueError("target_stage must be an IFTStageEvidence")
    _require_enum(reported_reason, IFTTerminationReason, "reported_reason")
    _require_enum(value_origin, ValueOrigin, "value_origin")
    if value_origin not in {ValueOrigin.SOURCE_REPORTED, ValueOrigin.PROVIDER_DERIVED}:
        raise ValueError(
            "IFT termination ingestion requires source-reported or provider-derived data"
        )
    protocol = target_stage.protocol
    identity = IFT30_15MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"ift30-15-termination:{target_stage.observation.observation_id.value}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=IFT30_15_CONSTRUCT,
            test_family=IFT30_15_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=IFT_TERMINATION_MEASURAND,
            metric_definition=IFT_TERMINATION_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=_acquisition_identity(source_artifact, acquisition),
        processing=FieldTestingProcessingIdentity(
            registered_operation=IFT_TEST_SOURCE_OPERATION,
            method_parameters=(
                MetadataEntry("termination_reason", reported_reason.value),
                MetadataEntry(
                    "target_stage_observation_id", target_stage.observation.observation_id.qualified
                ),
            ),
            processing_state=_source_processing_state(value_origin),
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
        ),
        version=VersionIdentity(
            processing_method=IFT_TEST_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"ift30-15-termination:{target_stage.observation.observation_id.value}"
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:termination"),
        value=CategoricalValue(reported_reason.value),
        unit=None,
        classification=ScientificClassification(value_origin, ()),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    observation = build_field_testing_source_observation(
        observation_id=observation_id,
        context=target_stage.observation.context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )
    return observation


def build_ift_termination_evidence(
    *,
    termination_observation: ScientificMeasurementObservation,
    target_stage: IFTStageEvidence,
) -> IFTTerminationEvidence:
    """Normalize pre-existing source/provider termination evidence."""

    if not isinstance(target_stage, IFTStageEvidence):
        raise ValueError("target_stage must be an IFTStageEvidence")
    evidence = IFTTerminationEvidence(termination_observation)
    if evidence.target_stage_observation_id != target_stage.observation.observation_id:
        raise ValueError("termination evidence targets a different final stage")
    if evidence.observation.context != target_stage.observation.context:
        raise ValueError("termination evidence context does not match the target stage")
    termination_identity = evidence.observation.identity
    if not isinstance(termination_identity, IFT30_15MeasurementIdentity):
        raise ValueError("termination evidence requires IFT30_15MeasurementIdentity")
    if termination_identity.semantic.protocol_identity != target_stage.protocol:
        raise ValueError("termination evidence uses a different protocol")
    if _ift_source_key(evidence.observation) != _ift_source_key(target_stage.observation):
        raise ValueError("termination evidence must use the same source identity")
    return evidence


def build_ift_test_evidence(
    *,
    test_id: InstanceIdentifier,
    protocol: IFT30_15ProtocolIdentity,
    stages: tuple[IFTStageEvidence, ...],
    termination: IFTTerminationEvidence,
) -> IFTTestEvidence:
    if not isinstance(stages, tuple) or not stages:
        raise ValueError("stages must be a non-empty tuple")
    return IFTTestEvidence(test_id, protocol, stages, termination)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VIFTResult:
    """VIFT result with final completed stage and source test evidence bound."""

    observation: ScientificMeasurementObservation
    test: IFTTestEvidence

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.test, IFTTestEvidence, "test")
        identity = self.observation.identity
        if not isinstance(identity, IFT30_15MeasurementIdentity):
            raise ValueError("VIFT result requires IFT30_15MeasurementIdentity")
        if identity.semantic.metric_definition != VIFT_METRIC:
            raise ValueError("VIFT result has the wrong metric")
        if identity.processing.registered_operation != VIFT_OPERATION:
            raise ValueError("VIFT result operation is not registered")
        if self.observation.result.unit != KILOMETER_PER_HOUR:
            raise ValueError("VIFT must use km/h")
        output_runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(output_runs) != 1:
            raise ValueError("VIFT must preserve one output processing run")
        if any(
            not any(
                edge.from_id == source.observation_id.qualified
                and edge.to_id == output_runs[0].processing_run_id.qualified
                for edge in self.observation.provenance.lineage_edges
            )
            for source in self.test.source_observations
        ):
            raise ValueError("VIFT result is missing source lineage")
        final = self.test.final_completed_stage
        if _numeric_scalar(self.observation) != final.target_stage_velocity_kmh:
            raise ValueError("VIFT scalar does not equal the final completed stage velocity")
        params = {
            entry.key: entry.value
            for entry in self.observation.identity.processing.method_parameters
        }
        if params.get("final_completed_stage") != final.stage_index:
            raise ValueError("VIFT final stage is not preserved in processing identity")

    @property
    def value_kmh(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def final_completed_stage(self) -> int:
        return self.test.final_completed_stage.stage_index


def calculate_vift(
    test: IFTTestEvidence,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> VIFTResult | RefusalResult:
    """Calculate VIFT from complete source-qualified canonical stage evidence."""

    ids: tuple[InstanceIdentifier, ...] = ()
    if isinstance(test, IFTTestEvidence):
        ids = tuple(item.observation_id for item in test.source_observations)
    try:
        if not isinstance(test, IFTTestEvidence):
            raise ValueError("typed IFT test evidence is required")
        if test.protocol.reference != IFT30_15_PROTOCOL_V1:
            raise ValueError("VIFT requires the canonical 40 m 30-15 IFT protocol")
        ordered = tuple(sorted(test.stages, key=lambda item: item.stage_index))
        completed_indices = tuple(stage.stage_index for stage in ordered if stage.is_completed)
        if not completed_indices:
            raise ValueError("VIFT requires at least one completed stage")
        last_completed_index = max(completed_indices)
        if completed_indices != tuple(range(1, last_completed_index + 1)):
            raise ValueError("IFT stage completion has a missing or incomplete middle stage")
        if any(
            stage.is_completed and stage.stage_index > last_completed_index for stage in ordered
        ):
            raise ValueError("IFT stage completion ordering is inconsistent")
        final = test.final_completed_stage
        value = test.protocol.stage_velocity_kmh(final.stage_index)
        parameters = (
            MetadataEntry("equation", "8.0 + 0.5 * (final_completed_stage - 1)"),
            MetadataEntry("final_completed_stage", final.stage_index),
            MetadataEntry("termination_reason", test.termination.reason.value),
            MetadataEntry("test_id", test.test_id.qualified),
            MetadataEntry(
                "stage_observation_ids",
                ",".join(item.observation.observation_id.qualified for item in ordered),
            ),
            MetadataEntry(
                "termination_observation_id", test.termination.observation.observation_id.qualified
            ),
        )
        source_identity = final.observation.identity
        if not isinstance(source_identity, IFT30_15MeasurementIdentity):
            raise ValueError("IFT output requires IFT30_15MeasurementIdentity")
        identity = IFT30_15MeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                f"vift:{test.test_id.value}",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=IFT30_15_CONSTRUCT,
                test_family=IFT30_15_TEST_FAMILY,
                protocol=test.protocol.reference,
                measurand=VIFT_MEASURAND,
                metric_definition=VIFT_METRIC,
                protocol_identity=test.protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                estimator=VIFT_ESTIMATOR,
                registered_operation=VIFT_OPERATION,
                method_parameters=parameters,
                unit=KILOMETER_PER_HOUR,
                aggregation=None,
                filtering=_protocol_processing_components(test.protocol)[0],
                filtering_status=_protocol_processing_components(test.protocol)[1],
                smoothing=_protocol_processing_components(test.protocol)[2],
                interpolation=_protocol_processing_components(test.protocol)[3],
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=VIFT_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        output = _build_derived_observation(
            source_observations=test.source_observations,
            identity=identity,
            value=value,
            unit=KILOMETER_PER_HOUR,
            operation=VIFT_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
            extra_source_entities=(test.test_id,),
        )
        return VIFTResult(output, test)
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        return _refusal(
            "calculate VIFT from source-qualified 30-15 IFT stages",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )


def refuse_vift_as_vo2max(*, observation_ids: tuple[InstanceIdentifier, ...] = ()) -> RefusalResult:
    return _refusal(
        "relabel VIFT as VO2max",
        (RefusalReasonCode.MEASURAND_MISMATCH, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
        ("a direct or separately registered VO2max measurement/estimator",),
        observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        safe_descriptions=("VIFT remains the canonical 30-15 IFT last-completed-stage velocity",),
    )


def refuse_vift_as_mas(*, observation_ids: tuple[InstanceIdentifier, ...] = ()) -> RefusalResult:
    return _refusal(
        "relabel VIFT as maximal aerobic speed",
        (RefusalReasonCode.MEASURAND_MISMATCH, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
        ("a separately registered maximal-aerobic-speed protocol and estimator",),
        observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        safe_descriptions=("VIFT remains an intermittent shuttle-test performance outcome",),
    )


def refuse_vift_as_mss(*, observation_ids: tuple[InstanceIdentifier, ...] = ()) -> RefusalResult:
    return _refusal(
        "relabel VIFT as maximum sprint speed",
        (RefusalReasonCode.MEASURAND_MISMATCH, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
        ("a velocity-domain maximum sprint-speed source and estimator",),
        observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        safe_descriptions=("VIFT remains distinct from maximum sprint velocity",),
    )


ThirtyFifteenIFTProtocolIdentity = IFT30_15ProtocolIdentity
ThirtyFifteenIFTStageEvidence = IFTStageEvidence
ThirtyFifteenIFTTestEvidence = IFTTestEvidence


__all__ = [
    "IFT30_15ProtocolIdentity",
    "IFTRecoveryMode",
    "IFTStageCompletion",
    "IFTStageCompletionEvidence",
    "IFTStageEvidence",
    "IFTTerminationEvidence",
    "IFTTerminationReason",
    "IFTTestEvidence",
    "ThirtyFifteenIFTProtocolIdentity",
    "ThirtyFifteenIFTStageEvidence",
    "ThirtyFifteenIFTTestEvidence",
    "VIFTResult",
    "build_ift_stage_completion_source_observation",
    "build_ift_stage_evidence",
    "build_ift_stage_source_observation",
    "build_ift_termination_evidence",
    "build_ift_termination_source_observation",
    "build_ift_test_evidence",
    "calculate_vift",
    "ift30_15_protocol_v1",
    "qualify_ift_stage",
    "refuse_vift_as_mas",
    "refuse_vift_as_mss",
    "refuse_vift_as_vo2max",
]
