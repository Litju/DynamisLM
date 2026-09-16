"""Deterministic short-sprint timing, split, velocity and maximum-speed authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.field_testing._common import (
    FieldTestingScalarResult,
    FieldTestingSourceQualificationEvidence,
    _build_derived_observation,
    _finite,
    _numeric_scalar,
    _protocol_processing_components,
    _refusal,
    _require_qualified,
    build_field_testing_source_observation,
)
from dynamislm.measurement.field_testing.identity import (
    FieldTestArtifactStatus,
    FieldTestFamily,
    FieldTestingAcquisitionIdentity,
    FieldTestingAcquisitionRecord,
    FieldTestingDistanceDefinition,
    FieldTestingProcessingIdentity,
    FieldTestingProtocolAttribute,
    FieldTestingProtocolIdentity,
    FieldTestingSegmentDefinition,
    FieldTestingSemanticIdentity,
    FieldTestingSourceArtifact,
    FieldTestingSupport,
    FieldTestingTimebase,
    FieldTestProcessingState,
    FieldTestSensorModality,
    FieldTestSide,
    MaximumSprintVelocityMeasurementIdentity,
    ReactionTimeSemantics,
    SprintMeasurementIdentity,
    StartInitiationMode,
    TimingGateTopology,
)
from dynamislm.measurement.field_testing.registry import (
    FIELD_TEST_VELOCITY_SERIES_SCHEMA,
    FIELD_TESTING_REGISTRY_VERSION,
    FIELD_TESTING_SOFTWARE_VERSION,
    LINEAR_SPRINT_30M_PROTOCOL_V1,
    LINEAR_SPRINT_MEAN_OPERATION,
    MAXIMUM_SPRINT_VELOCITY_CONSTRUCT,
    MAXIMUM_SPRINT_VELOCITY_MEASURAND,
    MAXIMUM_SPRINT_VELOCITY_METRIC,
    MAXIMUM_SPRINT_VELOCITY_SOURCE_OPERATION,
    MAXIMUM_SPRINT_VELOCITY_TEST_FAMILY,
    MEAN_OF_THREE_QUALIFIED_10M_REFERENCE,
    MEAN_OF_THREE_QUALIFIED_TRIALS,
    METER_PER_SECOND,
    PHOTOCELL_GATE_FINISH_TRIGGER,
    PHOTOCELL_GATE_START_TRIGGER,
    SAMPLED_MAXIMUM_ESTIMATOR,
    SAMPLED_MAXIMUM_VELOCITY_OPERATION,
    SECOND,
    SEGMENT_AVERAGE_VELOCITY_ESTIMATOR,
    SEGMENT_AVERAGE_VELOCITY_MEASURAND,
    SEGMENT_AVERAGE_VELOCITY_METRIC,
    SHORT_LINEAR_SPRINT_CONSTRUCT,
    SHORT_LINEAR_SPRINT_PROTOCOL_V1,
    SHORT_LINEAR_SPRINT_TEST_FAMILY,
    SPLIT_TIME_MEASURAND,
    SPRINT_CUMULATIVE_SPLIT_ESTIMATOR,
    SPRINT_CUMULATIVE_SPLIT_METRIC,
    SPRINT_INTERVAL_SPLIT_ESTIMATOR,
    SPRINT_INTERVAL_SPLIT_METRIC,
    SPRINT_INTERVAL_SPLIT_OPERATION,
    SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION,
    SPRINT_TIMING_SOURCE_OPERATION,
    SPRINT_VELOCITY_CONSTRUCT,
    VELOCITY_SERIES_METRIC,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    SamplingCharacteristics,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_tuple_items,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import ProcessingRun
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult
from dynamislm.serialization import canonical_hash, register_serializable_type


class SprintSplitKind(StrEnum):
    """Marker values for cumulative versus interval timing."""

    CUMULATIVE = "CUMULATIVE"
    INTERVAL = "INTERVAL"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SprintSplitDefinition:
    """Exact one-dimensional cumulative or interval split definition."""

    kind: SprintSplitKind
    start_m: float
    end_m: float

    def __post_init__(self) -> None:
        try:
            kind = SprintSplitKind(self.kind)
        except ValueError as exc:
            raise ValueError("split kind must be CUMULATIVE or INTERVAL") from exc
        object.__setattr__(self, "kind", kind)
        start = _finite(self.start_m, "start_m")
        end = _finite(self.end_m, "end_m")
        if start < 0 or end <= start:
            raise ValueError("split must satisfy 0 <= start_m < end_m")
        if self.kind == SprintSplitKind.CUMULATIVE and start != 0:
            raise ValueError("cumulative split must start at 0 m")
        object.__setattr__(self, "start_m", start)
        object.__setattr__(self, "end_m", end)

    @property
    def distance_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def split_type(self) -> SprintSplitKind:
        return self.kind

    @property
    def is_cumulative(self) -> bool:
        return self.kind == SprintSplitKind.CUMULATIVE

    @property
    def is_interval(self) -> bool:
        return self.kind == SprintSplitKind.INTERVAL


def cumulative_split(end_m: float) -> SprintSplitDefinition:
    return SprintSplitDefinition(SprintSplitKind.CUMULATIVE, 0.0, end_m)


def interval_split(start_m: float, end_m: float) -> SprintSplitDefinition:
    return SprintSplitDefinition(SprintSplitKind.INTERVAL, start_m, end_m)


def short_linear_sprint_protocol_v1(
    *,
    reference: RegistryReference = SHORT_LINEAR_SPRINT_PROTOCOL_V1,
    protocol_version: str = FIELD_TESTING_REGISTRY_VERSION,
    start_position: str | None = None,
    start_line_offset_m: float | None = None,
    start_initiation_mode: StartInitiationMode | None = None,
    reaction_time_semantics: ReactionTimeSemantics | None = None,
    surface: str | None = None,
    environment: tuple[MetadataEntry, ...] | None = None,
    course_layout: tuple[FieldTestingProtocolAttribute, ...] | None = None,
    start_trigger: RegistryReference | None = None,
    finish_trigger: RegistryReference | None = None,
    timing_device: RegistryReference | None = None,
    provider: str | None = None,
    sensor_modality: FieldTestSensorModality = FieldTestSensorModality.UNKNOWN,
    gate_topology: TimingGateTopology | None = None,
    gate_height_m: float | None = None,
    sampling: SamplingCharacteristics | None = None,
    timebase: FieldTestingTimebase | None = None,
    filtering: tuple[RegistryReference, ...] | None = None,
    smoothing: RegistryReference | None = None,
    interpolation: RegistryReference | None = None,
    software: str | None = None,
    firmware: str | None = None,
    trial_selection: RegistryReference | None = None,
    repetition_selection: RegistryReference | None = None,
    side: FieldTestSide | None = None,
    turn_leg_convention: str | None = None,
    distance_definitions: tuple[FieldTestingDistanceDefinition, ...] | None = None,
    segment_definitions: tuple[FieldTestingSegmentDefinition, ...] | None = None,
) -> FieldTestingProtocolIdentity:
    """Build a registered short-sprint protocol without filling unknown fields."""

    from dynamislm.measurement.field_testing.identity import TimingGateTopology

    return FieldTestingProtocolIdentity(
        family=FieldTestFamily.SHORT_LINEAR_SPRINT,
        protocol_version=protocol_version,
        reference=reference,
        start_position=start_position,
        start_line_offset_m=start_line_offset_m,
        surface=surface,
        environment=environment,
        course_layout=course_layout,
        start_initiation_mode=start_initiation_mode or StartInitiationMode.UNKNOWN,
        reaction_time_semantics=reaction_time_semantics or ReactionTimeSemantics.UNKNOWN,
        start_trigger=start_trigger,
        finish_trigger=finish_trigger,
        timing_device=timing_device,
        provider=provider,
        sensor_modality=sensor_modality,
        gate_topology=gate_topology or TimingGateTopology.UNKNOWN,
        gate_height_m=gate_height_m,
        sampling=sampling,
        timebase=timebase,
        filtering=filtering,
        smoothing=smoothing,
        interpolation=interpolation,
        software=software,
        firmware=firmware,
        trial_selection=trial_selection,
        repetition_selection=repetition_selection,
        side=side,
        turn_leg_convention=turn_leg_convention,
        distance_definitions=distance_definitions,
        segment_definitions=segment_definitions,
    )


def linear_sprint_30m_protocol_v1() -> FieldTestingProtocolIdentity:
    """Return the registered 30 m sprint protocol used by COD deficit V1."""

    from dynamislm.measurement.field_testing.identity import (
        ReactionTimeSemantics,
        StartInitiationMode,
    )

    return FieldTestingProtocolIdentity(
        family=FieldTestFamily.SHORT_LINEAR_SPRINT,
        protocol_version=FIELD_TESTING_REGISTRY_VERSION,
        reference=LINEAR_SPRINT_30M_PROTOCOL_V1,
        start_position="standing",
        start_line_offset_m=0.30,
        start_initiation_mode=StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
        reaction_time_semantics=ReactionTimeSemantics.EXCLUDED,
        start_trigger=PHOTOCELL_GATE_START_TRIGGER,
        finish_trigger=PHOTOCELL_GATE_FINISH_TRIGGER,
        distance_definitions=(
            # The 0-10 m split is the exact COD-deficit reference; the full
            # 30 m protocol remains explicit even when only that split is used.
            # The named distances are not inferred from a scalar label.
            FieldTestingDistanceDefinition("sprint-30m", 30.0),
            FieldTestingDistanceDefinition("reference-0-10m", 10.0),
        ),
    )


def _source_processing_state(value_origin: ValueOrigin) -> FieldTestProcessingState:
    if value_origin is ValueOrigin.PROVIDER_DERIVED:
        return FieldTestProcessingState.PROVIDER_PROCESSED
    if value_origin is ValueOrigin.DYNAMISLM_DERIVED:
        return FieldTestProcessingState.DYNAMISLM_PROCESSED
    return FieldTestProcessingState.RAW_ACQUIRED


def _source_acquisition_identity(
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


def _timing_method_parameters(split: SprintSplitDefinition) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("split_kind", split.kind),
        MetadataEntry("split_start_m", split.start_m),
        MetadataEntry("split_end_m", split.end_m),
        MetadataEntry("equation", "source timing gate result in seconds"),
    )


def build_sprint_time_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    protocol: FieldTestingProtocolIdentity,
    split: SprintSplitDefinition,
    time_seconds: float,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.SOURCE_REPORTED,
    processing_run: ProcessingRun | None = None,
    software_version: str = FIELD_TESTING_SOFTWARE_VERSION,
) -> SprintTimeObservation:
    """Create a typed source timing observation; a scalar alone is insufficient."""

    if protocol.family is not FieldTestFamily.SHORT_LINEAR_SPRINT:
        raise ValueError("sprint timing requires a short-linear-sprint protocol")
    if protocol.reference is None:
        raise ValueError("sprint timing requires a registered protocol reference")
    _require_enum(value_origin, ValueOrigin, "value_origin")
    if value_origin in {
        ValueOrigin.DYNAMISLM_DERIVED,
        ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
        ValueOrigin.MODEL_ESTIMATE,
    }:
        raise ValueError("sprint source timing cannot use a derived or model origin")
    time_value = _finite(time_seconds, "time_seconds")
    if time_value <= 0:
        raise ValueError("sprint time must be positive")
    identity_id = ScientificIdentifier(
        "dynamislm",
        "measurement-identity",
        f"sprint-time:{split.kind.lower()}:{split.start_m:g}-{split.end_m:g}",
        FIELD_TESTING_REGISTRY_VERSION,
    )
    acquisition_identity = _source_acquisition_identity(source_artifact, acquisition)
    event_definitions = tuple(
        item for item in (protocol.start_trigger, protocol.finish_trigger) if item is not None
    )
    processing_parameters = _timing_method_parameters(split)
    processing = FieldTestingProcessingIdentity(
        event_definitions=event_definitions,
        estimator=(
            SPRINT_CUMULATIVE_SPLIT_ESTIMATOR
            if split.is_cumulative
            else SPRINT_INTERVAL_SPLIT_ESTIMATOR
        ),
        registered_operation=SPRINT_TIMING_SOURCE_OPERATION,
        method_parameters=processing_parameters,
        unit=SECOND,
        trial_selection=protocol.trial_selection,
        timebase=protocol.timebase or acquisition.timebase,
        filtering=_protocol_processing_components(protocol)[0],
        filtering_status=_protocol_processing_components(protocol)[1],
        smoothing=_protocol_processing_components(protocol)[2],
        interpolation=_protocol_processing_components(protocol)[3],
        processing_state=_source_processing_state(value_origin),
    )
    identity = SprintMeasurementIdentity(
        identity_id=identity_id,
        semantic=FieldTestingSemanticIdentity(
            construct=SHORT_LINEAR_SPRINT_CONSTRUCT,
            test_family=SHORT_LINEAR_SPRINT_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=SPLIT_TIME_MEASURAND,
            metric_definition=(
                SPRINT_CUMULATIVE_SPLIT_METRIC
                if split.is_cumulative
                else SPRINT_INTERVAL_SPLIT_METRIC
            ),
            protocol_identity=protocol,
        ),
        acquisition=acquisition_identity,
        processing=processing,
        version=VersionIdentity(
            processing_method=SPRINT_TIMING_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=software_version,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:time"),
        value=ScalarValue(time_value),
        unit=SECOND,
        classification=ScientificClassification(
            value_origin, (ScientificRole.PERFORMANCE_OUTCOME,)
        ),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    observation = build_field_testing_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        processing_run=processing_run,
    )
    return SprintTimeObservation(observation=observation, split=split)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SprintTimeObservation:
    """Typed sprint time whose split and source timing identity are inseparable."""

    observation: ScientificMeasurementObservation
    split: SprintSplitDefinition
    source_qualification: FieldTestingSourceQualificationEvidence | None = None

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.split, SprintSplitDefinition, "split")
        identity = self.observation.identity
        if not isinstance(identity, SprintMeasurementIdentity):
            raise ValueError("sprint time requires SprintMeasurementIdentity")
        protocol = identity.semantic.protocol_identity
        if protocol is None or protocol.family is not FieldTestFamily.SHORT_LINEAR_SPRINT:
            raise ValueError("sprint time requires a short-linear-sprint protocol identity")
        expected_metric = (
            SPRINT_CUMULATIVE_SPLIT_METRIC
            if self.split.is_cumulative
            else SPRINT_INTERVAL_SPLIT_METRIC
        )
        if identity.semantic.metric_definition != expected_metric:
            raise ValueError("sprint split kind and metric definition do not agree")
        allowed_operations = {
            SPRINT_TIMING_SOURCE_OPERATION,
            SPRINT_INTERVAL_SPLIT_OPERATION,
            LINEAR_SPRINT_MEAN_OPERATION,
        }
        if identity.processing.registered_operation not in allowed_operations:
            raise ValueError("sprint time uses an unregistered timing operation")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
            ValueOrigin.DYNAMISLM_DERIVED,
        }:
            raise ValueError("sprint time cannot be a model estimate")
        if (
            self.observation.result.classification.value_origin is not ValueOrigin.DYNAMISLM_DERIVED
            and identity.processing.registered_operation != SPRINT_TIMING_SOURCE_OPERATION
        ):
            raise ValueError("source sprint time must use the source timing operation")
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            params.get("split_kind") != self.split.kind
            or params.get("split_start_m") != self.split.start_m
            or params.get("split_end_m") != self.split.end_m
        ):
            raise ValueError("sprint split is not preserved in processing identity")
        if self.observation.result.unit != SECOND:
            raise ValueError("sprint time must use seconds")
        value = _numeric_scalar(self.observation)
        if value <= 0:
            raise ValueError("sprint time must be positive")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("sprint time must be valid")
        if self.source_qualification is not None:
            _require_qualified(self.source_qualification, self.observation)
        if (
            self.observation.result.classification.value_origin is not ValueOrigin.DYNAMISLM_DERIVED
            and self.observation.context.trial_id is None
        ):
            raise ValueError("source sprint time must preserve a trial context")

    @property
    def source_time_seconds(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def context(self) -> ObservationContext:
        return self.observation.context

    @property
    def identity(self) -> SprintMeasurementIdentity:
        identity = self.observation.identity
        assert isinstance(identity, SprintMeasurementIdentity)
        return identity

    @property
    def is_source_qualified(self) -> bool:
        return (
            self.source_qualification is not None
            and self.source_qualification.status.value == "QUALIFIED"
        )


def _sprint_source_key(observation: SprintTimeObservation) -> object:
    identity = observation.identity
    acquisition = identity.acquisition
    processing = identity.processing
    return {
        "protocol": identity.semantic.protocol_identity,
        "construct": identity.semantic.construct,
        "measurand": identity.semantic.measurand,
        "device": acquisition.device,
        "provider": acquisition.provider,
        "sensor_modality": acquisition.sensor_modality,
        "sampling": acquisition.sampling,
        "timebase": acquisition.timebase or processing.timebase,
        "axis_or_frame": acquisition.axis_or_frame,
        "sensor_channel": acquisition.sensor_channel,
        "event_definitions": processing.event_definitions,
        "filtering": processing.filtering,
        "filtering_status": processing.filtering_status,
        "smoothing": processing.smoothing,
        "interpolation": processing.interpolation,
        "processing_state": processing.processing_state,
        "value_origin": observation.observation.result.classification.value_origin,
        "version": identity.version,
    }


def _same_sprint_scope(observations: tuple[SprintTimeObservation, ...]) -> bool:
    first = observations[0].context
    return all(
        observation.context.athlete_id == first.athlete_id
        and observation.context.session_id == first.session_id
        and observation.context.test_instance_id == first.test_instance_id
        and observation.context.observed_at == first.observed_at
        and observation.context.population_context == first.population_context
        and observation.context.environment == first.environment
        for observation in observations[1:]
    )


def aggregate_linear_sprint_30m_reference(
    trials: tuple[SprintTimeObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> SprintTimeObservation | RefusalResult:
    """Build the registered mean 0-10 m reference from three qualified trials."""

    ids = tuple(
        trial.observation.observation_id
        for trial in trials
        if isinstance(trial, SprintTimeObservation)
    )
    try:
        if not isinstance(trials, tuple) or len(trials) != 3:
            raise ValueError("the registered linear reference requires exactly three trials")
        if any(not isinstance(trial, SprintTimeObservation) for trial in trials):
            raise ValueError("linear reference trials must be typed sprint observations")
        if any(not trial.split.is_cumulative or trial.split.end_m != 10.0 for trial in trials):
            raise ValueError("linear reference trials must be cumulative 0-10 m observations")
        if any(
            trial.identity.semantic.protocol != LINEAR_SPRINT_30M_PROTOCOL_V1 for trial in trials
        ):
            raise ValueError("linear reference requires the registered 30 m sprint protocol")
        if len({trial.context.trial_id for trial in trials}) != 3:
            raise ValueError("linear reference trials must have unique trial IDs")
        if any(trial.source_qualification is None for trial in trials):
            raise ValueError("linear reference requires source-qualified trials")
        if not _same_sprint_scope(trials):
            raise ValueError("linear reference trials must share athlete/session/test scope")
        if any(_sprint_source_key(trial) != _sprint_source_key(trials[0]) for trial in trials[1:]):
            raise ValueError("linear reference trials must share timing/device/processing identity")
        value = math.fsum(trial.source_time_seconds for trial in trials) / 3.0
        source_identity = trials[0].identity
        protocol = source_identity.semantic.protocol_identity
        assert protocol is not None
        parameters = (
            MetadataEntry("split_kind", SprintSplitKind.CUMULATIVE),
            MetadataEntry("split_start_m", 0.0),
            MetadataEntry("split_end_m", 10.0),
            MetadataEntry("equation", "mean(three qualified cumulative 0-10 m times)"),
            MetadataEntry("selection_rule", MEAN_OF_THREE_QUALIFIED_10M_REFERENCE.stable_id),
            MetadataEntry("source_observation_ids", ",".join(item.qualified for item in ids)),
        )
        identity = SprintMeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                "linear-sprint-mean-0-10m-reference",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=SHORT_LINEAR_SPRINT_CONSTRUCT,
                test_family=SHORT_LINEAR_SPRINT_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=SPLIT_TIME_MEASURAND,
                metric_definition=SPRINT_CUMULATIVE_SPLIT_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                estimator=SPRINT_CUMULATIVE_SPLIT_ESTIMATOR,
                registered_operation=LINEAR_SPRINT_MEAN_OPERATION,
                method_parameters=parameters,
                unit=SECOND,
                timebase=source_identity.processing.timebase,
                trial_selection=MEAN_OF_THREE_QUALIFIED_TRIALS,
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=LINEAR_SPRINT_MEAN_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        source_observations_list: list[ScientificMeasurementObservation] = []
        for trial in trials:
            assert trial.source_qualification is not None
            source_observations_list.extend(
                (trial.observation, trial.source_qualification.qualification_observation)
            )
        source_observations = tuple(source_observations_list)
        output = _build_derived_observation(
            source_observations=source_observations,
            identity=identity,
            value=value,
            unit=SECOND,
            operation=LINEAR_SPRINT_MEAN_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
        )
        return SprintTimeObservation(output, cumulative_split(10.0))
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "aggregate the registered mean 0-10 m linear sprint reference",
            (
                RefusalReasonCode.TRIAL_SET_INCOMPLETE,
                RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,
            ),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def _same_sprint_context(left: SprintTimeObservation, right: SprintTimeObservation) -> bool:
    left_context = left.context
    right_context = right.context
    return (
        left_context.athlete_id == right_context.athlete_id
        and left_context.session_id == right_context.session_id
        and left_context.test_instance_id == right_context.test_instance_id
        and left_context.trial_id == right_context.trial_id
        and left_context.observed_at == right_context.observed_at
        and left_context.population_context == right_context.population_context
        and left_context.environment == right_context.environment
    )


def _interval_parameters(
    left: SprintTimeObservation, right: SprintTimeObservation
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("split_kind", SprintSplitKind.INTERVAL),
        MetadataEntry("split_start_m", left.split.end_m),
        MetadataEntry("split_end_m", right.split.end_m),
        MetadataEntry("equation", "t[0,b] - t[0,a]"),
        MetadataEntry("left_source_observation_id", left.observation.observation_id.qualified),
        MetadataEntry("right_source_observation_id", right.observation.observation_id.qualified),
        MetadataEntry("start_distance_m", left.split.end_m),
        MetadataEntry("end_distance_m", right.split.end_m),
    )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class SegmentAverageVelocityResult(FieldTestingScalarResult):
    """Exact segment-average velocity bound to its interval and segment."""

    interval: SprintTimeObservation
    segment: FieldTestingSegmentDefinition

    def __post_init__(self) -> None:
        FieldTestingScalarResult.__post_init__(self)
        if self.metric != SEGMENT_AVERAGE_VELOCITY_METRIC:
            raise ValueError("segment-average result has the wrong metric")
        identity = self.observation.identity
        if not isinstance(identity, SprintMeasurementIdentity):
            raise ValueError("segment-average result requires SprintMeasurementIdentity")
        if identity.processing.registered_operation != SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION:
            raise ValueError("segment-average result operation is not registered")
        if self.observation.result.unit != METER_PER_SECOND:
            raise ValueError("segment-average result must use m/s")
        if (
            self.interval.split.start_m != self.segment.start_m
            or self.interval.split.end_m != self.segment.end_m
        ):
            raise ValueError("segment-average result is bound to a different segment")
        expected = self.segment.distance_m / self.interval.source_time_seconds
        if self.value != expected:
            raise ValueError("segment-average result scalar does not reproduce")
        if self.observation.context != self.interval.context:
            raise ValueError("segment-average result context was rebound")


def derive_interval_split(
    start_cumulative: SprintTimeObservation,
    end_cumulative: SprintTimeObservation,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> SprintTimeObservation | RefusalResult:
    """Derive an interval split only from compatible cumulative observations."""

    ids: tuple[InstanceIdentifier, ...] = ()
    if isinstance(start_cumulative, SprintTimeObservation):
        ids += (start_cumulative.observation.observation_id,)
    if isinstance(end_cumulative, SprintTimeObservation):
        ids += (end_cumulative.observation.observation_id,)
    try:
        if not isinstance(start_cumulative, SprintTimeObservation) or not isinstance(
            end_cumulative, SprintTimeObservation
        ):
            raise ValueError("typed cumulative sprint observations are required")
        if not start_cumulative.split.is_cumulative or not end_cumulative.split.is_cumulative:
            raise ValueError("interval splits require cumulative source observations")
        if start_cumulative.split.start_m != 0 or end_cumulative.split.start_m != 0:
            raise ValueError("cumulative source observations must start at 0 m")
        if end_cumulative.split.end_m <= start_cumulative.split.end_m:
            raise ValueError("interval distance must be positive and ordered")
        if not _same_sprint_context(start_cumulative, end_cumulative):
            raise ValueError("interval split requires the same athlete/session/test/trial context")
        if (
            start_cumulative.identity.semantic.protocol_identity
            != end_cumulative.identity.semantic.protocol_identity
        ):
            raise ValueError("interval split requires one exact protocol identity")
        if _sprint_source_key(start_cumulative) != _sprint_source_key(end_cumulative):
            raise ValueError(
                "interval split requires one exact timing system and processing identity"
            )
        elapsed = end_cumulative.source_time_seconds - start_cumulative.source_time_seconds
        if elapsed <= 0 or not math.isfinite(elapsed):
            raise ValueError("interval elapsed time must be positive")
        source_identity = end_cumulative.identity
        protocol = source_identity.semantic.protocol_identity
        assert protocol is not None
        parameters = _interval_parameters(start_cumulative, end_cumulative)
        processing = FieldTestingProcessingIdentity(
            estimator=SPRINT_INTERVAL_SPLIT_ESTIMATOR,
            registered_operation=SPRINT_INTERVAL_SPLIT_OPERATION,
            method_parameters=parameters,
            unit=SECOND,
            timebase=source_identity.processing.timebase,
            filtering=source_identity.processing.filtering,
            filtering_status=source_identity.processing.filtering_status,
            smoothing=source_identity.processing.smoothing,
            interpolation=source_identity.processing.interpolation,
            processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
        )
        identity = SprintMeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                "sprint-interval-split",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=SHORT_LINEAR_SPRINT_CONSTRUCT,
                test_family=SHORT_LINEAR_SPRINT_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=SPLIT_TIME_MEASURAND,
                metric_definition=SPRINT_INTERVAL_SPLIT_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=processing,
            version=VersionIdentity(
                processing_method=SPRINT_INTERVAL_SPLIT_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        output = _build_derived_observation(
            source_observations=(start_cumulative.observation, end_cumulative.observation),
            identity=identity,
            value=elapsed,
            unit=SECOND,
            operation=SPRINT_INTERVAL_SPLIT_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
        )
        return SprintTimeObservation(
            observation=output,
            split=interval_split(start_cumulative.split.end_m, end_cumulative.split.end_m),
        )
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "derive interval sprint split from cumulative timing",
            (
                RefusalReasonCode.METRIC_DEFINITION_MISMATCH,
                RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,
                RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,
            ),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            safe_descriptions=(
                "the individual cumulative source times remain separately describable",
            ),
        )


def derive_segment_average_velocity(
    interval: SprintTimeObservation,
    segment: FieldTestingSegmentDefinition,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> SegmentAverageVelocityResult | RefusalResult:
    """Compute distance divided by exact interval time in m/s."""

    ids = (
        (interval.observation.observation_id,)
        if isinstance(interval, SprintTimeObservation)
        else ()
    )
    try:
        if not isinstance(interval, SprintTimeObservation):
            raise ValueError("typed sprint interval observation is required")
        if not interval.split.is_interval:
            raise ValueError("segment-average velocity requires an interval split")
        _require_instance(segment, FieldTestingSegmentDefinition, "segment")
        if segment.start_m != interval.split.start_m or segment.end_m != interval.split.end_m:
            raise ValueError("segment definition must equal the exact interval split")
        elapsed = interval.source_time_seconds
        if elapsed <= 0:
            raise ValueError("interval elapsed time must be positive")
        value = segment.distance_m / elapsed
        source_identity = interval.identity
        protocol = source_identity.semantic.protocol_identity
        assert protocol is not None
        parameters = (
            MetadataEntry("equation", "segment_distance_m / interval_elapsed_time_s"),
            MetadataEntry("source_observation_id", interval.observation.observation_id.qualified),
            MetadataEntry("segment_name", segment.name),
            MetadataEntry("segment_start_m", segment.start_m),
            MetadataEntry("segment_end_m", segment.end_m),
        )
        processing = FieldTestingProcessingIdentity(
            estimator=SEGMENT_AVERAGE_VELOCITY_ESTIMATOR,
            registered_operation=SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION,
            method_parameters=parameters,
            unit=METER_PER_SECOND,
            timebase=source_identity.processing.timebase,
            filtering=source_identity.processing.filtering,
            filtering_status=source_identity.processing.filtering_status,
            smoothing=source_identity.processing.smoothing,
            interpolation=source_identity.processing.interpolation,
            processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
        )
        identity = SprintMeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                "segment-average-velocity",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=SPRINT_VELOCITY_CONSTRUCT,
                test_family=SHORT_LINEAR_SPRINT_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=SEGMENT_AVERAGE_VELOCITY_MEASURAND,
                metric_definition=SEGMENT_AVERAGE_VELOCITY_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=processing,
            version=VersionIdentity(
                processing_method=SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        output = _build_derived_observation(
            source_observations=(interval.observation,),
            identity=identity,
            value=value,
            unit=METER_PER_SECOND,
            operation=SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
        )
        return SegmentAverageVelocityResult(
            observation=output,
            metric=SEGMENT_AVERAGE_VELOCITY_METRIC,
            source_observations=(interval.observation,),
            interval=interval,
            segment=segment,
        )
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "calculate segment-average sprint velocity",
            (RefusalReasonCode.MISSING_DISTANCE, RefusalReasonCode.ZERO_DURATION),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SprintVelocitySample:
    timestamp_s: float
    velocity_m_per_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_s", _finite(self.timestamp_s, "timestamp_s"))
        object.__setattr__(
            self, "velocity_m_per_s", _finite(self.velocity_m_per_s, "velocity_m_per_s")
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SprintVelocitySeries:
    """Delivered velocity series kept outside scalar MeasurementResult."""

    source_artifact_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_acquisition_id: InstanceIdentifier
    samples: tuple[SprintVelocitySample, ...]
    timebase: FieldTestingTimebase
    support: FieldTestingSupport
    unit: UnitReference = METER_PER_SECOND
    series_digest: str | None = None
    sampling: SamplingCharacteristics | None = None

    def __post_init__(self) -> None:
        _require_instance(self.source_artifact_id, InstanceIdentifier, "source_artifact_id")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("source_artifact_id must identify an artifact")
        _require_instance(
            self.source_measurement_identity_id,
            ScientificIdentifier,
            "source_measurement_identity_id",
        )
        _require_instance(self.source_acquisition_id, InstanceIdentifier, "source_acquisition_id")
        if self.source_acquisition_id.instance_type != "acquisition":
            raise ValueError("source_acquisition_id must identify an acquisition")
        _require_tuple_items(self.samples, SprintVelocitySample, "samples")
        if not self.samples:
            raise ValueError("velocity series requires at least one sample")
        _require_instance(self.timebase, FieldTestingTimebase, "timebase")
        _require_instance(self.support, FieldTestingSupport, "support")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_instance(self.unit, UnitReference, "unit")
        if self.support.end_index >= len(self.samples):
            raise ValueError("velocity support lies outside the delivered series")
        for index, sample in enumerate(self.samples):
            expected_time = self.timebase.time_at(index)
            if sample.timestamp_s != expected_time:
                raise ValueError("velocity sample timestamp does not match its timebase")
        if (
            self.timebase.time_at(self.support.start_index) != self.support.start_time_s
            or self.timebase.time_at(self.support.end_index) != self.support.end_time_s
        ):
            raise ValueError("velocity support times must equal exact source sample times")
        if self.support.end_time_s < self.support.start_time_s:
            raise ValueError("velocity support must be ordered")
        pairs = tuple((sample.timestamp_s, sample.velocity_m_per_s) for sample in self.samples)
        expected_digest = canonical_hash(
            {
                "samples": pairs,
                "timebase": self.timebase,
                "support": self.support,
                "unit": self.unit,
                "sampling": self.sampling,
            }
        )
        if self.series_digest is None:
            object.__setattr__(self, "series_digest", expected_digest)
        elif self.series_digest != expected_digest:
            raise ValueError("series_digest does not match samples, timebase, support and unit")

    @property
    def canonical_content_digest(self) -> str:
        assert self.series_digest is not None
        return self.series_digest


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SprintVelocitySeriesEvidence:
    """Velocity-domain source evidence for qualified maximum-speed calculation."""

    observation: ScientificMeasurementObservation
    series: SprintVelocitySeries
    source_artifact: FieldTestingSourceArtifact
    acquisition: FieldTestingAcquisitionRecord

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.series, SprintVelocitySeries, "series")
        _require_instance(self.source_artifact, FieldTestingSourceArtifact, "source_artifact")
        _require_instance(self.acquisition, FieldTestingAcquisitionRecord, "acquisition")
        if (
            self.source_artifact.status is not FieldTestArtifactStatus.VERIFIED
            or not self.source_artifact.immutable
        ):
            raise ValueError("velocity series artifact must be immutable and verified")
        if self.source_artifact.artifact_id != self.series.source_artifact_id:
            raise ValueError("velocity series artifact does not match source evidence")
        if self.source_artifact.content_digest != self.series.canonical_content_digest:
            raise ValueError("velocity series artifact digest does not match the delivered series")
        if self.acquisition.acquisition_id != self.series.source_acquisition_id:
            raise ValueError("velocity series acquisition does not match source evidence")
        if self.acquisition.sampling != self.series.sampling:
            raise ValueError("velocity series sampling does not match source acquisition")
        if self.source_artifact.artifact_id not in tuple(
            artifact.artifact_id for artifact in self.observation.provenance.source_artifacts
        ):
            raise ValueError("velocity source observation omits its source artifact")
        if self.acquisition.acquisition_id not in tuple(
            item.acquisition_id for item in self.observation.provenance.acquisitions
        ):
            raise ValueError("velocity source observation omits its source acquisition")
        identity = self.observation.identity
        if not isinstance(identity, MaximumSprintVelocityMeasurementIdentity):
            raise ValueError("velocity series requires MaximumSprintVelocityMeasurementIdentity")
        if identity.semantic.metric_definition != VELOCITY_SERIES_METRIC:
            raise ValueError("velocity series has the wrong metric identity")
        if identity.acquisition.raw_artifact != self.source_artifact.artifact_id:
            raise ValueError("velocity identity does not name source artifact")
        if identity.acquisition.acquisition_instance_id != self.acquisition.acquisition_id:
            raise ValueError("velocity identity does not name source acquisition")
        if identity.acquisition.source_series_digest != self.series.canonical_content_digest:
            raise ValueError("velocity identity does not preserve source series digest")
        if identity.acquisition.timebase != self.series.timebase:
            raise ValueError("velocity identity does not preserve source timebase")
        protocol = identity.semantic.protocol_identity
        if protocol is None:
            raise ValueError("velocity source requires protocol identity")
        if identity.processing.filtering != (protocol.filtering or ()):
            raise ValueError("velocity identity does not preserve protocol filtering")
        if identity.processing.smoothing != protocol.smoothing:
            raise ValueError("velocity identity does not preserve protocol smoothing")
        if identity.processing.interpolation != protocol.interpolation:
            raise ValueError("velocity identity does not preserve protocol interpolation")
        if (
            identity.acquisition.device != self.acquisition.device
            or identity.acquisition.provider != self.acquisition.provider
            or identity.acquisition.sensor_modality != self.acquisition.sensor_modality
            or identity.acquisition.sampling != self.acquisition.sampling
            or identity.acquisition.axis_or_frame != self.acquisition.axis_or_frame
        ):
            raise ValueError("velocity identity and acquisition describe different systems")
        if self.observation.result.unit != METER_PER_SECOND:
            raise ValueError("velocity source series must use m/s")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("velocity source series cannot be a model estimate")
        value = self.observation.result.value
        if not isinstance(value, StructuredOutputReference):
            raise ValueError("velocity source result must be a structured artifact reference")
        if value.artifact_id != self.source_artifact.artifact_id:
            raise ValueError("velocity source result points to a different artifact")

    @property
    def identity(self) -> MaximumSprintVelocityMeasurementIdentity:
        identity = self.observation.identity
        assert isinstance(identity, MaximumSprintVelocityMeasurementIdentity)
        return identity


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MaximumSprintVelocityResult:
    """Sampled maximum result retaining the exact velocity-series evidence."""

    observation: ScientificMeasurementObservation
    evidence: SprintVelocitySeriesEvidence

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.evidence, SprintVelocitySeriesEvidence, "evidence")
        identity = self.observation.identity
        if not isinstance(identity, MaximumSprintVelocityMeasurementIdentity):
            raise ValueError("maximum sprint velocity requires its typed identity")
        if identity.semantic.metric_definition != MAXIMUM_SPRINT_VELOCITY_METRIC:
            raise ValueError("maximum sprint velocity has the wrong metric")
        if identity.processing.estimator != SAMPLED_MAXIMUM_ESTIMATOR:
            raise ValueError("maximum sprint velocity must use SAMPLED_MAXIMUM")
        if identity.processing.registered_operation != SAMPLED_MAXIMUM_VELOCITY_OPERATION:
            raise ValueError("maximum sprint velocity operation is not registered")
        if (
            identity.processing.filtering != self.evidence.identity.processing.filtering
            or identity.processing.filtering_status
            != self.evidence.identity.processing.filtering_status
            or identity.processing.smoothing != self.evidence.identity.processing.smoothing
            or identity.processing.interpolation != self.evidence.identity.processing.interpolation
            or identity.processing.timebase != self.evidence.series.timebase
        ):
            raise ValueError("maximum sprint velocity output does not preserve processing identity")
        if self.observation.context != self.evidence.observation.context:
            raise ValueError("maximum sprint velocity output context was rebound")
        if self.observation.result.unit != METER_PER_SECOND:
            raise ValueError("maximum sprint velocity must use m/s")
        support = self.evidence.series.support
        values = self.evidence.series.samples[support.start_index : support.end_index + 1]
        expected = max(sample.velocity_m_per_s for sample in values)
        if _numeric_scalar(self.observation) != expected:
            raise ValueError(
                "maximum sprint velocity scalar does not reproduce from source samples"
            )
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        expected_index = next(
            support.start_index + offset
            for offset, sample in enumerate(values)
            if sample.velocity_m_per_s == expected
        )
        if (
            params.get("estimator") != SAMPLED_MAXIMUM_ESTIMATOR.stable_id
            or params.get("source_observation_id")
            != self.evidence.observation.observation_id.qualified
            or params.get("source_series_digest") != self.evidence.series.canonical_content_digest
            or params.get("support_id") != support.support_id.qualified
            or params.get("support_start_index") != support.start_index
            or params.get("support_end_index") != support.end_index
            or params.get("maximum_sample_index") != expected_index
        ):
            raise ValueError(
                "maximum sprint velocity output does not preserve source support/digest"
            )

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def metric(self) -> RegistryReference:
        return MAXIMUM_SPRINT_VELOCITY_METRIC

    @property
    def source_observations(self) -> tuple[ScientificMeasurementObservation, ...]:
        return (self.evidence.observation,)


def build_velocity_series_evidence(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    protocol: FieldTestingProtocolIdentity,
    series: SprintVelocitySeries,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    value_origin: ValueOrigin = ValueOrigin.PROVIDER_DERIVED,
    processing_run: ProcessingRun | None = None,
) -> SprintVelocitySeriesEvidence:
    """Create velocity-domain source evidence with exact series/artifact binding."""

    if protocol.family is not FieldTestFamily.MAXIMUM_SPRINT_VELOCITY:
        raise ValueError("velocity series requires a maximum-sprint-velocity protocol")
    if protocol.reference is None:
        raise ValueError("velocity series requires a registered protocol reference")
    if source_artifact.content_digest != series.canonical_content_digest:
        raise ValueError("source artifact digest must equal the exact velocity-series digest")
    identity = MaximumSprintVelocityMeasurementIdentity(
        identity_id=series.source_measurement_identity_id,
        semantic=FieldTestingSemanticIdentity(
            construct=MAXIMUM_SPRINT_VELOCITY_CONSTRUCT,
            test_family=MAXIMUM_SPRINT_VELOCITY_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=MAXIMUM_SPRINT_VELOCITY_MEASURAND,
            metric_definition=VELOCITY_SERIES_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=FieldTestingAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=source_artifact.artifact_id,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            acquisition_instance_id=acquisition.acquisition_id,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=series.timebase,
            axis_or_frame=acquisition.axis_or_frame,
            source_series_digest=series.canonical_content_digest,
        ),
        processing=FieldTestingProcessingIdentity(
            registered_operation=MAXIMUM_SPRINT_VELOCITY_SOURCE_OPERATION,
            method_parameters=(
                MetadataEntry("series_digest", series.canonical_content_digest),
                MetadataEntry("support_id", series.support.support_id.qualified),
                MetadataEntry("support_start_index", series.support.start_index),
                MetadataEntry("support_end_index", series.support.end_index),
            ),
            unit=METER_PER_SECOND,
            timebase=series.timebase,
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
            processing_state=_source_processing_state(value_origin),
        ),
        version=VersionIdentity(
            processing_method=MAXIMUM_SPRINT_VELOCITY_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:velocity-series"),
        value=StructuredOutputReference(
            artifact_id=source_artifact.artifact_id,
            schema=FIELD_TEST_VELOCITY_SERIES_SCHEMA,
        ),
        unit=METER_PER_SECOND,
        classification=ScientificClassification(
            value_origin, (ScientificRole.PERFORMANCE_OUTCOME,)
        ),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    observation = build_field_testing_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        processing_run=processing_run,
    )
    return SprintVelocitySeriesEvidence(
        observation=observation,
        series=series,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )


def sampled_maximum_velocity(
    evidence: SprintVelocitySeriesEvidence,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> MaximumSprintVelocityResult | RefusalResult:
    """Return the maximum sampled velocity over the exact registered support."""

    ids = (
        (evidence.observation.observation_id,)
        if isinstance(evidence, SprintVelocitySeriesEvidence)
        else ()
    )
    try:
        if not isinstance(evidence, SprintVelocitySeriesEvidence):
            raise ValueError("typed velocity-series evidence is required")
        values = evidence.series.samples[
            evidence.series.support.start_index : evidence.series.support.end_index + 1
        ]
        if not values:
            raise ValueError("registered velocity support contains no samples")
        max_value = max(sample.velocity_m_per_s for sample in values)
        sample_offset = next(
            offset for offset, sample in enumerate(values) if sample.velocity_m_per_s == max_value
        )
        sample_index = evidence.series.support.start_index + sample_offset
        parameters = (
            MetadataEntry("equation", "max(sampled velocity over exact support)"),
            MetadataEntry("estimator", SAMPLED_MAXIMUM_ESTIMATOR.stable_id),
            MetadataEntry("source_observation_id", evidence.observation.observation_id.qualified),
            MetadataEntry("source_series_digest", evidence.series.canonical_content_digest),
            MetadataEntry("support_id", evidence.series.support.support_id.qualified),
            MetadataEntry("support_start_index", evidence.series.support.start_index),
            MetadataEntry("support_end_index", evidence.series.support.end_index),
            MetadataEntry("maximum_sample_index", sample_index),
        )
        source_identity = evidence.identity
        protocol = source_identity.semantic.protocol_identity
        assert protocol is not None
        identity = MaximumSprintVelocityMeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                "maximum-sprint-velocity-sampled",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=MAXIMUM_SPRINT_VELOCITY_CONSTRUCT,
                test_family=MAXIMUM_SPRINT_VELOCITY_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=MAXIMUM_SPRINT_VELOCITY_MEASURAND,
                metric_definition=MAXIMUM_SPRINT_VELOCITY_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                estimator=SAMPLED_MAXIMUM_ESTIMATOR,
                registered_operation=SAMPLED_MAXIMUM_VELOCITY_OPERATION,
                method_parameters=parameters,
                unit=METER_PER_SECOND,
                filtering=source_identity.processing.filtering,
                filtering_status=source_identity.processing.filtering_status,
                smoothing=source_identity.processing.smoothing,
                interpolation=source_identity.processing.interpolation,
                timebase=evidence.series.timebase,
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=SAMPLED_MAXIMUM_VELOCITY_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        output = _build_derived_observation(
            source_observations=(evidence.observation,),
            identity=identity,
            value=max_value,
            unit=METER_PER_SECOND,
            operation=SAMPLED_MAXIMUM_VELOCITY_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
            extra_source_entities=(evidence.series.support.support_id,),
        )
        return MaximumSprintVelocityResult(observation=output, evidence=evidence)
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        return _refusal(
            "calculate maximum sampled sprint velocity",
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH, RefusalReasonCode.UNKNOWN_INTERPOLATION),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )


def refuse_segment_average_velocity_as_max_speed(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "relabel timing-gate segment-average velocity as maximum sprint velocity",
        (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
        ("SEGMENT_AVERAGE_VELOCITY is not a velocity-domain maximum estimator",),
        observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        safe_descriptions=("the exact segment-average velocity remains describable in m/s",),
    )


def refuse_sampled_maximum_as_sustained_maximum(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "relabel sampled maximum sprint velocity as sustained maximum sprint velocity",
        (RefusalReasonCode.ESTIMATOR_MISMATCH, RefusalReasonCode.NO_REGISTERED_OPERATION),
        ("a registered dwell duration and sustained-speed estimator",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=("the sampled maximum remains available as its registered estimator",),
    )


def refuse_sprint_acceleration(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "derive sprint acceleration from split-average velocities",
        (RefusalReasonCode.NO_REGISTERED_OPERATION, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
        ("qualified time-resolved position/velocity data and a registered acceleration method",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=(
            "cumulative and interval split times remain describable",
            "segment-average velocity remains distinct from acceleration",
        ),
    )


# Readable aliases for callers using noun-first names.
calculate_interval_split = derive_interval_split
calculate_segment_average_velocity = derive_segment_average_velocity
calculate_sampled_maximum_velocity = sampled_maximum_velocity
SprintTimeEvidence = SprintTimeObservation
MaximumSprintVelocityEvidence = SprintVelocitySeriesEvidence
SegmentAverageVelocityObservation = SegmentAverageVelocityResult
calculate_sprint_interval_split = derive_interval_split
calculate_maximum_sprint_velocity = sampled_maximum_velocity
__all__ = [
    "MaximumSprintVelocityEvidence",
    "MaximumSprintVelocityResult",
    "SegmentAverageVelocityObservation",
    "SegmentAverageVelocityResult",
    "SprintSplitDefinition",
    "SprintSplitKind",
    "SprintTimeEvidence",
    "SprintTimeObservation",
    "SprintVelocitySample",
    "SprintVelocitySeries",
    "SprintVelocitySeriesEvidence",
    "aggregate_linear_sprint_30m_reference",
    "build_sprint_time_observation",
    "build_velocity_series_evidence",
    "calculate_interval_split",
    "calculate_maximum_sprint_velocity",
    "calculate_sampled_maximum_velocity",
    "calculate_segment_average_velocity",
    "calculate_sprint_interval_split",
    "cumulative_split",
    "derive_interval_split",
    "derive_segment_average_velocity",
    "interval_split",
    "linear_sprint_30m_protocol_v1",
    "refuse_sampled_maximum_as_sustained_maximum",
    "refuse_segment_average_velocity_as_max_speed",
    "refuse_sprint_acceleration",
    "sampled_maximum_velocity",
    "short_linear_sprint_protocol_v1",
]
