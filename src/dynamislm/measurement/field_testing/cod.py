"""Standard 505 change-of-direction and registered COD-deficit authority."""

from __future__ import annotations

import math
from dataclasses import dataclass

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
    build_source_qualification_observation,
)
from dynamislm.measurement.field_testing.identity import (
    FieldTestFamily,
    FieldTestingAcquisitionIdentity,
    FieldTestingAcquisitionRecord,
    FieldTestingDistanceDefinition,
    FieldTestingMeasurementIdentity,
    FieldTestingProcessingIdentity,
    FieldTestingProtocolAttribute,
    FieldTestingProtocolIdentity,
    FieldTestingSegmentDefinition,
    FieldTestingSemanticIdentity,
    FieldTestingSourceArtifact,
    FieldTestProcessingState,
    FieldTestQualificationStatus,
    FieldTestSensorModality,
    FieldTestSide,
    ReactionTimeSemantics,
    Standard505MeasurementIdentity,
    StartInitiationMode,
    TimingGateTopology,
)
from dynamislm.measurement.field_testing.registry import (
    COD_DEFICIT_ESTIMATOR,
    COD_DEFICIT_MEASURAND,
    COD_DEFICIT_METRIC,
    COD_DEFICIT_OPERATION,
    FIELD_TESTING_REGISTRY_VERSION,
    FIELD_TESTING_SOFTWARE_VERSION,
    LINEAR_SPRINT_30M_PROTOCOL_V1,
    MEAN_OF_THREE_QUALIFIED_TRIALS,
    METER,
    PHOTOCELL_GATE_FINISH_TRIGGER,
    PHOTOCELL_GATE_START_TRIGGER,
    SECOND,
    STANDARD_505_CONSTRUCT,
    STANDARD_505_MEAN_OPERATION,
    STANDARD_505_PROTOCOL_V1,
    STANDARD_505_SOURCE_OPERATION,
    STANDARD_505_TEST_FAMILY,
    STANDARD_505_TIME_MEASURAND,
    STANDARD_505_TIME_METRIC,
)
from dynamislm.measurement.field_testing.sprint import SprintTimeObservation
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ScientificIdentifier,
    VersionIdentity,
    _require_enum,
    _require_instance,
    _require_text,
    _require_tuple_items,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
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


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class Standard505ProtocolIdentity(FieldTestingProtocolIdentity):
    """Exact 505 geometry and timing-section identity."""

    approach_distance_m: float
    timed_entry_distance_m: float
    turn_angle_deg: float
    timed_exit_distance_m: float
    turn_line: str
    timing_start_before_turn_m: float
    timing_finish: str

    def __post_init__(self) -> None:
        FieldTestingProtocolIdentity.__post_init__(self)
        if self.family is not FieldTestFamily.STANDARD_505:
            raise ValueError("Standard505ProtocolIdentity requires the standard 505 family")
        for name in (
            "approach_distance_m",
            "timed_entry_distance_m",
            "turn_angle_deg",
            "timed_exit_distance_m",
            "timing_start_before_turn_m",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        _require_text(self.turn_line, "turn_line")
        _require_text(self.timing_finish, "timing_finish")
        if self.reference == STANDARD_505_PROTOCOL_V1:
            expected: dict[str, object] = {
                "approach_distance_m": 15.0,
                "timed_entry_distance_m": 5.0,
                "turn_angle_deg": 180.0,
                "timed_exit_distance_m": 5.0,
                "timing_start_before_turn_m": 5.0,
                "turn_line": "5 m turn line",
                "timing_finish": "return through same timing gate",
                "start_position": "standing",
                "start_line_offset_m": 0.30,
                "start_initiation_mode": StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
                "reaction_time_semantics": ReactionTimeSemantics.EXCLUDED,
                "sensor_modality": FieldTestSensorModality.TIMING_GATE,
                "trial_selection": MEAN_OF_THREE_QUALIFIED_TRIALS,
                "turn_leg_convention": "foot_plant_at_turn_line",
                "start_trigger": PHOTOCELL_GATE_START_TRIGGER,
                "finish_trigger": PHOTOCELL_GATE_FINISH_TRIGGER,
            }
            for name, expected_value in expected.items():
                if getattr(self, name) != expected_value:
                    raise ValueError(f"canonical standard 505 protocol has a different {name}")

    @property
    def timed_distance_m(self) -> float:
        return self.timed_entry_distance_m + self.timed_exit_distance_m


def standard_505_protocol_v1() -> Standard505ProtocolIdentity:
    """Return the one registered standard 505 V1 protocol."""

    return Standard505ProtocolIdentity(
        family=FieldTestFamily.STANDARD_505,
        protocol_version=FIELD_TESTING_REGISTRY_VERSION,
        reference=STANDARD_505_PROTOCOL_V1,
        surface=None,
        environment=None,
        course_layout=(
            FieldTestingProtocolAttribute("approach_distance_m", 15.0, METER),
            FieldTestingProtocolAttribute("timed_entry_distance_m", 5.0, METER),
            FieldTestingProtocolAttribute("turn_angle_deg", 180.0, None),
            FieldTestingProtocolAttribute("timed_exit_distance_m", 5.0, METER),
            FieldTestingProtocolAttribute("timing_start_before_turn_m", 5.0, METER),
            FieldTestingProtocolAttribute("timing_finish", "return through same timing gate"),
        ),
        start_position="standing",
        start_line_offset_m=0.30,
        start_initiation_mode=StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
        reaction_time_semantics=ReactionTimeSemantics.EXCLUDED,
        start_trigger=PHOTOCELL_GATE_START_TRIGGER,
        finish_trigger=PHOTOCELL_GATE_FINISH_TRIGGER,
        provider=None,
        sensor_modality=FieldTestSensorModality.TIMING_GATE,
        gate_topology=TimingGateTopology.UNKNOWN,
        timing_device=None,
        trial_selection=MEAN_OF_THREE_QUALIFIED_TRIALS,
        side=None,
        turn_leg_convention="foot_plant_at_turn_line",
        distance_definitions=(
            FieldTestingDistanceDefinition("approach", 15.0),
            FieldTestingDistanceDefinition("timed_entry", 5.0),
            FieldTestingDistanceDefinition("timed_exit", 5.0),
            FieldTestingDistanceDefinition("timed_result", 10.0),
        ),
        segment_definitions=(
            FieldTestingSegmentDefinition("timed_entry", 0.0, 5.0),
            FieldTestingSegmentDefinition("timed_exit", 5.0, 10.0),
        ),
        approach_distance_m=15.0,
        timed_entry_distance_m=5.0,
        turn_angle_deg=180.0,
        timed_exit_distance_m=5.0,
        turn_line="5 m turn line",
        timing_start_before_turn_m=5.0,
        timing_finish="return through same timing gate",
    )


def _505_parameters(
    protocol: Standard505ProtocolIdentity, side: FieldTestSide
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("approach_distance_m", protocol.approach_distance_m),
        MetadataEntry("timed_entry_distance_m", protocol.timed_entry_distance_m),
        MetadataEntry("turn_angle_deg", protocol.turn_angle_deg),
        MetadataEntry("timed_exit_distance_m", protocol.timed_exit_distance_m),
        MetadataEntry("timing_start_before_turn_m", protocol.timing_start_before_turn_m),
        MetadataEntry("timing_finish", protocol.timing_finish),
        MetadataEntry("turn_side", side.value),
        MetadataEntry("turn_leg_convention", protocol.turn_leg_convention),
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
class Standard505TrialObservation:
    """One side-specific standard 505 trial, optionally source-qualified."""

    observation: ScientificMeasurementObservation
    side: FieldTestSide
    source_qualification: FieldTestingSourceQualificationEvidence | None = None

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_enum(self.side, FieldTestSide, "side")
        identity = self.observation.identity
        if not isinstance(identity, Standard505MeasurementIdentity):
            raise ValueError("505 trial requires Standard505MeasurementIdentity")
        protocol = identity.semantic.protocol_identity
        if not isinstance(protocol, Standard505ProtocolIdentity):
            raise ValueError("505 trial requires Standard505ProtocolIdentity")
        if identity.semantic.metric_definition != STANDARD_505_TIME_METRIC:
            raise ValueError("505 trial has the wrong metric identity")
        if identity.processing.registered_operation != STANDARD_505_SOURCE_OPERATION:
            raise ValueError("505 source trial uses an unregistered operation")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("505 source trial cannot be a model estimate")
        if self.observation.result.unit != SECOND:
            raise ValueError("505 time must use seconds")
        if _numeric_scalar(self.observation) <= 0:
            raise ValueError("505 time must be positive")
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if params.get("turn_side") != self.side.value:
            raise ValueError("505 side is not preserved in processing identity")
        if self.observation.context.trial_id is None:
            raise ValueError("505 source trial must preserve a trial context")
        if self.source_qualification is not None:
            _require_qualified(self.source_qualification, self.observation)

    @property
    def time_seconds(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def protocol(self) -> Standard505ProtocolIdentity:
        identity = self.observation.identity
        assert isinstance(identity, Standard505MeasurementIdentity)
        protocol = identity.semantic.protocol_identity
        assert isinstance(protocol, Standard505ProtocolIdentity)
        return protocol

    @property
    def is_source_qualified(self) -> bool:
        return (
            self.source_qualification is not None
            and self.source_qualification.status is FieldTestQualificationStatus.QUALIFIED
        )


def build_standard_505_trial_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    protocol: Standard505ProtocolIdentity,
    side: FieldTestSide,
    time_seconds: float,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    processing_run: ProcessingRun | None = None,
    qualification_status: FieldTestQualificationStatus | None = None,
) -> Standard505TrialObservation:
    """Create a typed standard 505 source trial; no side is inferred."""

    if not isinstance(protocol, Standard505ProtocolIdentity):
        raise ValueError("protocol must be a Standard505ProtocolIdentity")
    _require_enum(side, FieldTestSide, "side")
    value = _finite(time_seconds, "time_seconds")
    if value <= 0:
        raise ValueError("505 time must be positive")
    if protocol.reference is None:
        raise ValueError("505 trial requires a registered protocol")
    parameters = _505_parameters(protocol, side)
    identity = Standard505MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"standard-505:{side.value.lower()}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=STANDARD_505_CONSTRUCT,
            test_family=STANDARD_505_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=STANDARD_505_TIME_MEASURAND,
            metric_definition=STANDARD_505_TIME_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=_acquisition_identity(source_artifact, acquisition),
        processing=FieldTestingProcessingIdentity(
            event_definitions=tuple(
                item
                for item in (protocol.start_trigger, protocol.finish_trigger)
                if item is not None
            ),
            registered_operation=STANDARD_505_SOURCE_OPERATION,
            method_parameters=parameters,
            unit=SECOND,
            trial_selection=protocol.trial_selection,
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
            processing_state=FieldTestProcessingState.RAW_ACQUIRED,
        ),
        version=VersionIdentity(
            processing_method=STANDARD_505_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:505"),
        value=ScalarValue(value),
        unit=SECOND,
        classification=ScientificClassification(
            ValueOrigin.SOURCE_REPORTED, (ScientificRole.PERFORMANCE_OUTCOME,)
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
    trial = Standard505TrialObservation(observation=observation, side=side)
    if qualification_status is not None:
        qualification = build_source_qualification_observation(
            target_observation=observation,
            status=qualification_status,
            source_artifact=source_artifact,
            acquisition=acquisition,
        )
        return Standard505TrialObservation(
            observation=observation,
            side=side,
            source_qualification=qualification,
        )
    return trial


def qualify_standard_505_trial(
    trial: Standard505TrialObservation,
    *,
    status: FieldTestQualificationStatus,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
) -> Standard505TrialObservation:
    if not isinstance(trial, Standard505TrialObservation):
        raise ValueError("trial must be a Standard505TrialObservation")
    qualification = build_source_qualification_observation(
        target_observation=trial.observation,
        status=status,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )
    return Standard505TrialObservation(
        observation=trial.observation,
        side=trial.side,
        source_qualification=qualification,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class Standard505Result:
    """Mean-of-three source-qualified 505 result for one explicit side."""

    observation: ScientificMeasurementObservation
    side: FieldTestSide
    trials: tuple[Standard505TrialObservation, ...]

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_enum(self.side, FieldTestSide, "side")
        _require_tuple_items(self.trials, Standard505TrialObservation, "trials")
        if len(self.trials) != 3:
            raise ValueError("standard 505 V1 result requires three trials")
        if any(not trial.is_source_qualified for trial in self.trials):
            raise ValueError("standard 505 result requires three source-qualified trials")
        if any(trial.side is not self.side for trial in self.trials):
            raise ValueError("505 result trials must use one exact side")
        if any(
            _cod_source_method_key(trial.observation)
            != _cod_source_method_key(self.trials[0].observation)
            for trial in self.trials[1:]
        ):
            raise ValueError("505 result trials must share timing-device processing identity")
        identity = self.observation.identity
        if not isinstance(identity, Standard505MeasurementIdentity):
            raise ValueError("505 result requires Standard505MeasurementIdentity")
        if not isinstance(identity.semantic.protocol_identity, Standard505ProtocolIdentity):
            raise ValueError("505 result requires Standard505ProtocolIdentity")
        if self.observation.context.trial_id is not None:
            raise ValueError("505 aggregate context must be trial-free")
        if identity.processing.registered_operation != STANDARD_505_MEAN_OPERATION:
            raise ValueError("505 result operation is not registered")
        if identity.semantic.metric_definition != STANDARD_505_TIME_METRIC:
            raise ValueError("505 result has the wrong metric")
        if (
            _numeric_scalar(self.observation)
            != math.fsum(trial.time_seconds for trial in self.trials) / 3.0
        ):
            raise ValueError("505 result scalar does not reproduce from its trials")
        params = {
            entry.key: entry.value
            for entry in self.observation.identity.processing.method_parameters
        }
        if params.get("aggregation_rule") != MEAN_OF_THREE_QUALIFIED_TRIALS.stable_id:
            raise ValueError("505 result does not preserve the registered aggregation rule")

    @property
    def time_seconds(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def protocol(self) -> Standard505ProtocolIdentity:
        identity = self.observation.identity
        assert isinstance(identity, Standard505MeasurementIdentity)
        protocol = identity.semantic.protocol_identity
        assert isinstance(protocol, Standard505ProtocolIdentity)
        return protocol


def aggregate_standard_505_trials(
    trials: tuple[Standard505TrialObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> Standard505Result | RefusalResult:
    """Aggregate exactly three source-qualified trials for one side."""

    ids = tuple(
        trial.observation.observation_id
        for trial in trials
        if isinstance(trial, Standard505TrialObservation)
    )
    try:
        if not isinstance(trials, tuple) or len(trials) != 3:
            raise ValueError("the registered 505 selection requires exactly three trials")
        if any(not isinstance(trial, Standard505TrialObservation) for trial in trials):
            raise ValueError("505 trials must be typed")
        if len({trial.observation.context.trial_id for trial in trials}) != 3:
            raise ValueError("505 trials must have unique trial IDs")
        if any(not trial.is_source_qualified for trial in trials):
            raise ValueError("all 505 trials must be source-qualified")
        first = trials[0]
        if any(trial.side is not first.side for trial in trials[1:]):
            raise ValueError("505 aggregation cannot combine left and right trials")
        if any(trial.protocol != first.protocol for trial in trials[1:]):
            raise ValueError("505 aggregation requires one exact protocol identity")
        if any(
            _cod_source_method_key(trial.observation) != _cod_source_method_key(first.observation)
            for trial in trials[1:]
        ):
            raise ValueError("505 aggregation requires one timing-device processing identity")
        first_context = first.observation.context
        if any(
            trial.observation.context.athlete_id != first_context.athlete_id
            or trial.observation.context.session_id != first_context.session_id
            or trial.observation.context.test_instance_id != first_context.test_instance_id
            or trial.observation.context.observed_at != first_context.observed_at
            or trial.observation.context.population_context != first_context.population_context
            or trial.observation.context.environment != first_context.environment
            for trial in trials[1:]
        ):
            raise ValueError("505 trials must share one athlete/session/test scope")
        value = math.fsum(trial.time_seconds for trial in trials) / 3.0
        source_identity = first.observation.identity
        assert isinstance(source_identity, Standard505MeasurementIdentity)
        protocol = first.protocol
        parameters = (
            MetadataEntry("equation", "mean(three source-qualified 505 times)"),
            MetadataEntry("aggregation_rule", MEAN_OF_THREE_QUALIFIED_TRIALS.stable_id),
            MetadataEntry("turn_side", first.side.value),
            MetadataEntry("source_observation_ids", ",".join(item.qualified for item in ids)),
        )
        identity = Standard505MeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                f"standard-505-mean:{first.side.value.lower()}",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=STANDARD_505_CONSTRUCT,
                test_family=STANDARD_505_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=STANDARD_505_TIME_MEASURAND,
                metric_definition=STANDARD_505_TIME_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                registered_operation=STANDARD_505_MEAN_OPERATION,
                method_parameters=parameters,
                unit=SECOND,
                trial_selection=MEAN_OF_THREE_QUALIFIED_TRIALS,
                filtering=_protocol_processing_components(protocol)[0],
                filtering_status=_protocol_processing_components(protocol)[1],
                smoothing=_protocol_processing_components(protocol)[2],
                interpolation=_protocol_processing_components(protocol)[3],
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=STANDARD_505_MEAN_OPERATION,
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
            operation=STANDARD_505_MEAN_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
        )
        return Standard505Result(output, first.side, trials)
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "aggregate source-qualified standard 505 trials",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def _cod_source_method_key(observation: ScientificMeasurementObservation) -> object:
    identity = observation.identity
    if not isinstance(identity, FieldTestingMeasurementIdentity):
        raise ValueError("COD source must use FieldTestingMeasurementIdentity")
    acquisition = identity.acquisition
    return (
        acquisition.device,
        acquisition.provider,
        acquisition.sensor_modality,
        acquisition.sampling,
        acquisition.axis_or_frame,
        acquisition.sensor_channel,
        identity.processing.event_definitions,
        identity.processing.filtering,
        identity.processing.filtering_status,
        identity.processing.smoothing,
        identity.processing.interpolation,
        identity.processing.processing_state,
        observation.result.classification.value_origin,
        identity.version.software_version,
        identity.version.hardware_firmware,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class CODDeficitResult(FieldTestingScalarResult):
    """Registered COD deficit bound to its standard 505 and linear sources."""

    standard_505: Standard505Result
    linear_sprint_reference: SprintTimeObservation

    def __post_init__(self) -> None:
        FieldTestingScalarResult.__post_init__(self)
        if self.metric != COD_DEFICIT_METRIC:
            raise ValueError("COD deficit result has the wrong metric")
        identity = self.observation.identity
        if not isinstance(identity, Standard505MeasurementIdentity):
            raise ValueError("COD deficit result requires Standard505MeasurementIdentity")
        if identity.processing.registered_operation != COD_DEFICIT_OPERATION:
            raise ValueError("COD deficit result operation is not registered")
        if self.observation.result.unit != SECOND:
            raise ValueError("COD deficit result must use seconds")
        if not isinstance(self.standard_505, Standard505Result) or not isinstance(
            self.linear_sprint_reference, SprintTimeObservation
        ):
            raise ValueError("COD deficit result requires typed source results")
        expected = self.standard_505.time_seconds - self.linear_sprint_reference.source_time_seconds
        if self.value != expected:
            raise ValueError("COD deficit result scalar does not reproduce")
        if self.observation.context.athlete_id != self.standard_505.observation.context.athlete_id:
            raise ValueError("COD deficit result athlete context was rebound")
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            params.get("standard_505_observation_id")
            != self.standard_505.observation.observation_id.qualified
            or params.get("linear_reference_observation_id")
            != self.linear_sprint_reference.observation.observation_id.qualified
            or params.get("turn_side") != self.standard_505.side.value
        ):
            raise ValueError("COD deficit result does not preserve both source identities")


def calculate_cod_deficit(
    standard_505: Standard505Result,
    linear_sprint_reference: SprintTimeObservation,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> CODDeficitResult | RefusalResult:
    """Compute mean standard-505 time minus the registered mean 0-10 m time."""

    ids: tuple[InstanceIdentifier, ...] = ()
    if isinstance(standard_505, Standard505Result):
        ids += (standard_505.observation.observation_id,)
    if hasattr(linear_sprint_reference, "observation"):
        ids += (linear_sprint_reference.observation.observation_id,)
    try:
        if not isinstance(standard_505, Standard505Result):
            raise ValueError("typed standard 505 result is required")
        if not isinstance(linear_sprint_reference, SprintTimeObservation):
            raise ValueError("typed registered linear sprint reference is required")
        if standard_505.protocol.reference != STANDARD_505_PROTOCOL_V1:
            raise ValueError("COD deficit requires the canonical standard 505 V1 protocol")
        if (
            not linear_sprint_reference.split.is_cumulative
            or linear_sprint_reference.split.end_m != 10.0
            or linear_sprint_reference.identity.semantic.protocol != LINEAR_SPRINT_30M_PROTOCOL_V1
        ):
            raise ValueError("COD deficit requires the registered mean 0-10 m linear reference")
        linear_params = {
            item.key: item.value
            for item in linear_sprint_reference.identity.processing.method_parameters
        }
        if (
            linear_sprint_reference.identity.processing.trial_selection
            != MEAN_OF_THREE_QUALIFIED_TRIALS
        ):
            raise ValueError("COD deficit requires a mean-of-three qualified linear reference")
        if linear_params.get("selection_rule") is None:
            raise ValueError("linear reference selection rule is unresolved")
        left = standard_505.observation.context
        right = linear_sprint_reference.observation.context
        if (
            left.athlete_id != right.athlete_id
            or left.session_id != right.session_id
            or left.observed_at != right.observed_at
            or left.population_context != right.population_context
            or left.environment != right.environment
        ):
            raise ValueError("COD deficit requires one athlete/session/time/environment scope")
        if _cod_source_method_key(standard_505.observation) != _cod_source_method_key(
            linear_sprint_reference.observation
        ):
            raise ValueError("COD deficit requires compatible timing-device processing identity")
        value = standard_505.time_seconds - linear_sprint_reference.source_time_seconds
        if not math.isfinite(value):
            raise ValueError("COD deficit must be finite")
        protocol = standard_505.protocol
        parameters = (
            MetadataEntry("equation", "mean_505_time_s - mean_0_10m_linear_sprint_time_s"),
            MetadataEntry(
                "standard_505_observation_id", standard_505.observation.observation_id.qualified
            ),
            MetadataEntry(
                "linear_reference_observation_id",
                linear_sprint_reference.observation.observation_id.qualified,
            ),
            MetadataEntry("turn_side", standard_505.side.value),
            MetadataEntry("linear_reference_protocol", LINEAR_SPRINT_30M_PROTOCOL_V1.stable_id),
        )
        source_identity = standard_505.observation.identity
        if not isinstance(source_identity, Standard505MeasurementIdentity):
            raise ValueError("standard 505 output requires Standard505MeasurementIdentity")
        identity = Standard505MeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                f"505-cod-deficit:{standard_505.side.value.lower()}",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=STANDARD_505_CONSTRUCT,
                test_family=STANDARD_505_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=COD_DEFICIT_MEASURAND,
                metric_definition=COD_DEFICIT_METRIC,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                estimator=COD_DEFICIT_ESTIMATOR,
                registered_operation=COD_DEFICIT_OPERATION,
                method_parameters=parameters,
                unit=SECOND,
                filtering=_protocol_processing_components(protocol)[0],
                filtering_status=_protocol_processing_components(protocol)[1],
                smoothing=_protocol_processing_components(protocol)[2],
                interpolation=_protocol_processing_components(protocol)[3],
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=COD_DEFICIT_OPERATION,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        output = _build_derived_observation(
            source_observations=(standard_505.observation, linear_sprint_reference.observation),
            identity=identity,
            value=value,
            unit=SECOND,
            operation=COD_DEFICIT_OPERATION,
            parameters=parameters,
            output_observation_id=output_observation_id,
        )
        return CODDeficitResult(
            observation=output,
            metric=COD_DEFICIT_METRIC,
            source_observations=(standard_505.observation, linear_sprint_reference.observation),
            standard_505=standard_505,
            linear_sprint_reference=linear_sprint_reference,
        )
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "calculate registered 505 COD deficit",
            (
                RefusalReasonCode.METRIC_DEFINITION_MISMATCH,
                RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH,
                RefusalReasonCode.DEVICE_COMPARABILITY_NOT_ESTABLISHED,
            ),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            safe_descriptions=(
                "the standard 505 time and linear reference remain separately describable",
            ),
        )


def refuse_505_asymmetry(*, observation_ids: tuple[InstanceIdentifier, ...] = ()) -> RefusalResult:
    return _refusal(
        "calculate generic 505 asymmetry",
        (RefusalReasonCode.NO_REGISTERED_OPERATION, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
        ("one exact evidence-supported numerator, denominator and sign convention",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=("LEFT and RIGHT standard 505 results remain separately available",),
    )


def refuse_cod_deficit_as_turning_technique(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "interpret COD deficit as turning technique or injury risk",
        (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
        ("a separately registered biomechanical or causal interpretation",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=("COD deficit remains a derived performance quantity in seconds",),
    )


calculate_505_mean = aggregate_standard_505_trials
cod_deficit = calculate_cod_deficit
FiveOhFiveProtocolIdentity = Standard505ProtocolIdentity
FiveOhFiveTrialObservation = Standard505TrialObservation
FiveOhFiveResult = Standard505Result
Standard505Observation = Standard505TrialObservation
CODDeficitObservation = CODDeficitResult
__all__ = [
    "CODDeficitObservation",
    "CODDeficitResult",
    "FiveOhFiveProtocolIdentity",
    "FiveOhFiveResult",
    "FiveOhFiveTrialObservation",
    "Standard505Observation",
    "Standard505ProtocolIdentity",
    "Standard505Result",
    "Standard505TrialObservation",
    "aggregate_standard_505_trials",
    "build_standard_505_trial_observation",
    "calculate_505_mean",
    "calculate_cod_deficit",
    "cod_deficit",
    "qualify_standard_505_trial",
    "refuse_505_asymmetry",
    "refuse_cod_deficit_as_turning_technique",
    "standard_505_protocol_v1",
]
