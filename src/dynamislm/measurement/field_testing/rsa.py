"""Protocol-bound repeated-sprint ability (RSA) computations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.field_testing._common import (
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
    FieldTestingProcessingIdentity,
    FieldTestingProtocolAttribute,
    FieldTestingProtocolIdentity,
    FieldTestingSemanticIdentity,
    FieldTestingSourceArtifact,
    FieldTestProcessingState,
    FieldTestQualificationStatus,
    FieldTestSensorModality,
    ReactionTimeSemantics,
    RSAMeasurementIdentity,
    StartInitiationMode,
    TimingGateTopology,
)
from dynamislm.measurement.field_testing.registry import (
    COMPLETE_REGISTERED_REPETITIONS,
    FIELD_TESTING_REGISTRY_VERSION,
    FIELD_TESTING_SOFTWARE_VERSION,
    METER,
    PERCENT,
    PHOTOCELL_GATE_FINISH_TRIGGER,
    PHOTOCELL_GATE_START_TRIGGER,
    RSA_6X40_SHUTTLE_PROTOCOL_V1,
    RSA_BEST_TIME_METRIC,
    RSA_BEST_TIME_OPERATION,
    RSA_CONSTRUCT,
    RSA_MEAN_TIME_METRIC,
    RSA_MEAN_TIME_OPERATION,
    RSA_PERCENT_DECREMENT_ESTIMATOR,
    RSA_PERCENT_DECREMENT_METRIC,
    RSA_PERCENT_DECREMENT_OPERATION,
    RSA_SPRINT_SOURCE_OPERATION,
    RSA_SPRINT_TIME_MEASURAND,
    RSA_SPRINT_TIME_METRIC,
    RSA_TEST_FAMILY,
    RSA_TOTAL_TIME_METRIC,
    RSA_TOTAL_TIME_OPERATION,
    SECOND,
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


class RSAMovementMode(StrEnum):
    LINEAR = "LINEAR"
    SHUTTLE = "SHUTTLE"


class RSARecoveryMode(StrEnum):
    PASSIVE = "PASSIVE"
    ACTIVE_WALK = "ACTIVE_WALK"
    ACTIVE_JOG = "ACTIVE_JOG"
    PROTOCOL_DEFINED = "PROTOCOL_DEFINED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class RSAProtocolIdentity(FieldTestingProtocolIdentity):
    """RSA protocol identity; distance/recovery/repetition variants are distinct."""

    movement_mode: RSAMovementMode
    sprint_distance_m: float
    shuttle_layout: tuple[FieldTestingProtocolAttribute, ...] | None
    cod_count: int
    turn_angle_deg: float | None
    repetitions: int
    recovery_duration_s: float
    recovery_mode: RSARecoveryMode
    departure_interval_s: float | None = None

    def __post_init__(self) -> None:
        FieldTestingProtocolIdentity.__post_init__(self)
        if self.family is not FieldTestFamily.REPEATED_SPRINT_ABILITY:
            raise ValueError("RSAProtocolIdentity requires the RSA family")
        _require_enum(self.movement_mode, RSAMovementMode, "movement_mode")
        _require_enum(self.recovery_mode, RSARecoveryMode, "recovery_mode")
        sprint_distance = _finite(self.sprint_distance_m, "sprint_distance_m")
        recovery = _finite(self.recovery_duration_s, "recovery_duration_s")
        if sprint_distance <= 0 or recovery < 0:
            raise ValueError("RSA distance must be positive and recovery non-negative")
        object.__setattr__(self, "sprint_distance_m", sprint_distance)
        object.__setattr__(self, "recovery_duration_s", recovery)
        turn_angle = self.turn_angle_deg
        if turn_angle is not None:
            turn_angle = _finite(turn_angle, "turn_angle_deg")
            if turn_angle <= 0 or turn_angle > 360:
                raise ValueError("turn_angle_deg must be in (0, 360]")
            object.__setattr__(self, "turn_angle_deg", turn_angle)
        if self.movement_mode is RSAMovementMode.SHUTTLE and self.shuttle_layout is None:
            raise ValueError("shuttle RSA requires an explicit shuttle layout")
        if self.movement_mode is RSAMovementMode.LINEAR and self.shuttle_layout is not None:
            raise ValueError("linear RSA must not carry a shuttle layout")
        if type(self.cod_count) is not int or self.cod_count < 0:
            raise ValueError("cod_count must be a non-negative integer")
        if type(self.repetitions) is not int or self.repetitions < 1:
            raise ValueError("RSA repetitions must be a positive integer")
        if self.departure_interval_s is not None:
            departure = _finite(self.departure_interval_s, "departure_interval_s")
            if departure <= 0:
                raise ValueError("departure_interval_s must be positive")
            object.__setattr__(self, "departure_interval_s", departure)
        if self.shuttle_layout is not None:
            _require_tuple_items(
                self.shuttle_layout, FieldTestingProtocolAttribute, "shuttle_layout"
            )
        if self.reference == RSA_6X40_SHUTTLE_PROTOCOL_V1:
            expected = {
                "movement_mode": RSAMovementMode.SHUTTLE,
                "sprint_distance_m": 40.0,
                "cod_count": 1,
                "turn_angle_deg": 180.0,
                "repetitions": 6,
                "recovery_duration_s": 20.0,
                "recovery_mode": RSARecoveryMode.PASSIVE,
                "start_position": "standing",
                "start_line_offset_m": 0.30,
                "start_initiation_mode": StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
                "reaction_time_semantics": ReactionTimeSemantics.EXCLUDED,
                "sensor_modality": FieldTestSensorModality.TIMING_GATE,
                "start_trigger": PHOTOCELL_GATE_START_TRIGGER,
                "finish_trigger": PHOTOCELL_GATE_FINISH_TRIGGER,
            }
            for name, expected_value in expected.items():
                if getattr(self, name) != expected_value:
                    raise ValueError(f"canonical RSA protocol has a different {name}")
            expected_layout = (
                FieldTestingProtocolAttribute("outbound_distance_m", 20.0, METER),
                FieldTestingProtocolAttribute("return_distance_m", 20.0, METER),
            )
            if self.shuttle_layout != expected_layout:
                raise ValueError("canonical RSA protocol has a different shuttle layout")


def rsa_6x40m_shuttle_protocol_v1() -> RSAProtocolIdentity:
    """Return the registered six-by-40-m, 20-second-recovery RSA protocol."""

    return RSAProtocolIdentity(
        family=FieldTestFamily.REPEATED_SPRINT_ABILITY,
        protocol_version=FIELD_TESTING_REGISTRY_VERSION,
        reference=RSA_6X40_SHUTTLE_PROTOCOL_V1,
        start_position="standing",
        start_line_offset_m=0.30,
        start_initiation_mode=StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
        reaction_time_semantics=ReactionTimeSemantics.EXCLUDED,
        start_trigger=PHOTOCELL_GATE_START_TRIGGER,
        finish_trigger=PHOTOCELL_GATE_FINISH_TRIGGER,
        sensor_modality=FieldTestSensorModality.TIMING_GATE,
        gate_topology=TimingGateTopology.UNKNOWN,
        course_layout=(
            FieldTestingProtocolAttribute("outbound_distance_m", 20.0, METER),
            FieldTestingProtocolAttribute("return_distance_m", 20.0, METER),
            FieldTestingProtocolAttribute("turn_angle_deg", 180.0),
        ),
        distance_definitions=(),
        movement_mode=RSAMovementMode.SHUTTLE,
        sprint_distance_m=40.0,
        shuttle_layout=(
            FieldTestingProtocolAttribute("outbound_distance_m", 20.0, METER),
            FieldTestingProtocolAttribute("return_distance_m", 20.0, METER),
        ),
        cod_count=1,
        turn_angle_deg=180.0,
        repetitions=6,
        recovery_duration_s=20.0,
        recovery_mode=RSARecoveryMode.PASSIVE,
        departure_interval_s=None,
    )


def _rsa_parameters(
    protocol: RSAProtocolIdentity,
    set_id: InstanceIdentifier,
    sprint_index: int,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("set_id", set_id.qualified),
        MetadataEntry("sprint_index", sprint_index),
        MetadataEntry("sprint_distance_m", protocol.sprint_distance_m),
        MetadataEntry("repetitions", protocol.repetitions),
        MetadataEntry("recovery_duration_s", protocol.recovery_duration_s),
        MetadataEntry("recovery_mode", protocol.recovery_mode.value),
        MetadataEntry("movement_mode", protocol.movement_mode.value),
        MetadataEntry("cod_count", protocol.cod_count),
        MetadataEntry("turn_angle_deg", protocol.turn_angle_deg),
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
class RSARepetitionObservation:
    """One ordered, side-effect-free RSA sprint result."""

    observation: ScientificMeasurementObservation
    set_id: InstanceIdentifier
    sprint_index: int
    source_qualification: FieldTestingSourceQualificationEvidence | None = None

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.set_id, InstanceIdentifier, "set_id")
        if self.set_id.instance_type != "rsa-set":
            raise ValueError("set_id must identify an RSA set")
        if type(self.sprint_index) is not int or self.sprint_index < 1:
            raise ValueError("sprint_index must be a positive integer")
        identity = self.observation.identity
        if not isinstance(identity, RSAMeasurementIdentity):
            raise ValueError("RSA repetition requires RSAMeasurementIdentity")
        protocol = identity.semantic.protocol_identity
        if not isinstance(protocol, RSAProtocolIdentity):
            raise ValueError("RSA repetition requires RSAProtocolIdentity")
        if self.sprint_index > protocol.repetitions:
            raise ValueError("sprint_index exceeds protocol repetition count")
        if identity.semantic.metric_definition != RSA_SPRINT_TIME_METRIC:
            raise ValueError("RSA repetition has the wrong metric")
        if identity.processing.registered_operation != RSA_SPRINT_SOURCE_OPERATION:
            raise ValueError("RSA source repetition uses an unregistered operation")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("RSA source repetition cannot be a model estimate")
        if self.observation.result.unit != SECOND:
            raise ValueError("RSA repetition time must use seconds")
        if _numeric_scalar(self.observation) <= 0:
            raise ValueError("RSA repetition time must be positive")
        params = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            params.get("set_id") != self.set_id.qualified
            or params.get("sprint_index") != self.sprint_index
        ):
            raise ValueError("RSA repetition ordering is not preserved in processing identity")
        if self.observation.context.trial_id is None:
            raise ValueError("RSA repetition must preserve a trial context")
        if self.source_qualification is not None:
            _require_qualified(self.source_qualification, self.observation)

    @property
    def time_seconds(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def protocol(self) -> RSAProtocolIdentity:
        identity = self.observation.identity
        assert isinstance(identity, RSAMeasurementIdentity)
        protocol = identity.semantic.protocol_identity
        assert isinstance(protocol, RSAProtocolIdentity)
        return protocol

    @property
    def is_source_qualified(self) -> bool:
        return (
            self.source_qualification is not None
            and self.source_qualification.status is FieldTestQualificationStatus.QUALIFIED
        )


def build_rsa_repetition_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    protocol: RSAProtocolIdentity,
    set_id: InstanceIdentifier,
    sprint_index: int,
    time_seconds: float,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    processing_run: ProcessingRun | None = None,
    qualification_status: FieldTestQualificationStatus | None = None,
) -> RSARepetitionObservation:
    """Create a typed RSA repetition; no tuple of floats is authoritative."""

    if not isinstance(protocol, RSAProtocolIdentity):
        raise ValueError("protocol must be an RSAProtocolIdentity")
    if protocol.reference is None:
        raise ValueError("RSA repetition requires a registered protocol")
    _require_instance(set_id, InstanceIdentifier, "set_id")
    if set_id.instance_type != "rsa-set":
        raise ValueError("set_id must identify an RSA set")
    if type(sprint_index) is not int or not 1 <= sprint_index <= protocol.repetitions:
        raise ValueError("sprint_index must be within the registered repetition count")
    value = _finite(time_seconds, "time_seconds")
    if value <= 0:
        raise ValueError("RSA repetition time must be positive")
    parameters = _rsa_parameters(protocol, set_id, sprint_index)
    identity = RSAMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"rsa-sprint:{set_id.value}:{sprint_index}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=RSA_CONSTRUCT,
            test_family=RSA_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=RSA_SPRINT_TIME_MEASURAND,
            metric_definition=RSA_SPRINT_TIME_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=_acquisition_identity(source_artifact, acquisition),
        processing=FieldTestingProcessingIdentity(
            registered_operation=RSA_SPRINT_SOURCE_OPERATION,
            method_parameters=parameters,
            unit=SECOND,
            filtering=_protocol_processing_components(protocol)[0],
            filtering_status=_protocol_processing_components(protocol)[1],
            smoothing=_protocol_processing_components(protocol)[2],
            interpolation=_protocol_processing_components(protocol)[3],
            processing_state=FieldTestProcessingState.RAW_ACQUIRED,
        ),
        version=VersionIdentity(
            processing_method=RSA_SPRINT_SOURCE_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"{observation_id.value}:rsa"),
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
    repetition = RSARepetitionObservation(observation, set_id, sprint_index)
    if qualification_status is None:
        return repetition
    qualification = build_source_qualification_observation(
        target_observation=observation,
        status=qualification_status,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )
    return RSARepetitionObservation(observation, set_id, sprint_index, qualification)


def qualify_rsa_repetition(
    repetition: RSARepetitionObservation,
    *,
    status: FieldTestQualificationStatus,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
) -> RSARepetitionObservation:
    if not isinstance(repetition, RSARepetitionObservation):
        raise ValueError("repetition must be an RSARepetitionObservation")
    qualification = build_source_qualification_observation(
        target_observation=repetition.observation,
        status=status,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )
    return RSARepetitionObservation(
        repetition.observation,
        repetition.set_id,
        repetition.sprint_index,
        qualification,
    )


def _rsa_source_key(repetition: RSARepetitionObservation) -> object:
    identity = repetition.observation.identity
    if not isinstance(identity, RSAMeasurementIdentity):
        raise ValueError("RSA source must use RSAMeasurementIdentity")
    acquisition = identity.acquisition
    processing = identity.processing
    return (
        identity.semantic.protocol_identity,
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
        repetition.observation.result.classification.value_origin,
        identity.version.software_version,
        identity.version.hardware_firmware,
    )


def _validate_repetition_series(repetitions: tuple[RSARepetitionObservation, ...]) -> None:
    if not isinstance(repetitions, tuple) or not repetitions:
        raise ValueError("RSA requires an immutable tuple of repetitions")
    if any(not isinstance(item, RSARepetitionObservation) for item in repetitions):
        raise ValueError("RSA repetitions must be typed")
    first = repetitions[0]
    protocol = first.protocol
    if len(repetitions) != protocol.repetitions:
        raise ValueError("RSA repetition count does not match protocol")
    if {item.sprint_index for item in repetitions} != set(range(1, protocol.repetitions + 1)):
        raise ValueError("RSA repetitions must contain each unique index exactly once")
    if tuple(item.sprint_index for item in repetitions) != tuple(
        range(1, protocol.repetitions + 1)
    ):
        raise ValueError("RSA repetitions must be ordered by sprint index")
    if len({item.set_id for item in repetitions}) != 1:
        raise ValueError("RSA repetitions must belong to one set")
    if any(item.protocol != protocol for item in repetitions[1:]):
        raise ValueError("RSA repetitions must use one exact protocol identity")
    if any(not item.is_source_qualified for item in repetitions):
        raise ValueError("every RSA repetition must be source-qualified")
    first_context = first.observation.context
    for item in repetitions[1:]:
        context = item.observation.context
        if (
            context.athlete_id != first_context.athlete_id
            or context.session_id != first_context.session_id
            or context.test_instance_id != first_context.test_instance_id
            or context.observed_at != first_context.observed_at
            or context.population_context != first_context.population_context
            or context.environment != first_context.environment
        ):
            raise ValueError("RSA repetitions must share one athlete/session/test scope")
        if _rsa_source_key(item) != _rsa_source_key(first):
            raise ValueError("RSA repetitions must share timing/device/processing identity")


def _metric_spec(metric: RegistryReference) -> tuple[RegistryReference, str]:
    if metric == RSA_BEST_TIME_METRIC:
        return RSA_BEST_TIME_OPERATION, "min(sprint_times)"
    if metric == RSA_MEAN_TIME_METRIC:
        return RSA_MEAN_TIME_OPERATION, "sum(sprint_times) / number_of_sprints"
    if metric == RSA_TOTAL_TIME_METRIC:
        return RSA_TOTAL_TIME_OPERATION, "sum(sprint_times)"
    if metric == RSA_PERCENT_DECREMENT_METRIC:
        return RSA_PERCENT_DECREMENT_OPERATION, "100 * (total / (best * n) - 1)"
    raise ValueError("RSA metric is not registered")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RSAResult:
    """One distinct RSA aggregate result with complete repetition lineage."""

    observation: ScientificMeasurementObservation
    metric: RegistryReference
    repetitions: tuple[RSARepetitionObservation, ...]

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.metric, RegistryReference, "metric")
        _require_tuple_items(self.repetitions, RSARepetitionObservation, "repetitions")
        _validate_repetition_series(self.repetitions)
        operation, _ = _metric_spec(self.metric)
        identity = self.observation.identity
        if not isinstance(identity, RSAMeasurementIdentity):
            raise ValueError("RSA result requires RSAMeasurementIdentity")
        if self.observation.context.trial_id is not None:
            raise ValueError("RSA aggregate context must be trial-free")
        if identity.semantic.metric_definition != self.metric:
            raise ValueError("RSA result metric does not match identity")
        if identity.processing.registered_operation != operation:
            raise ValueError("RSA result operation does not match metric")
        run_ids = tuple(
            run.processing_run_id.qualified
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(run_ids) != 1:
            raise ValueError("RSA result must preserve one output processing run")
        if any(
            not any(
                edge.from_id == repetition.observation.observation_id.qualified
                and edge.to_id == run_ids[0]
                for edge in self.observation.provenance.lineage_edges
            )
            for repetition in self.repetitions
        ):
            raise ValueError("RSA result is missing a repetition lineage edge")
        values = tuple(item.time_seconds for item in self.repetitions)
        best = min(values)
        total = math.fsum(values)
        expected = {
            RSA_BEST_TIME_METRIC: best,
            RSA_MEAN_TIME_METRIC: total / len(values),
            RSA_TOTAL_TIME_METRIC: total,
            RSA_PERCENT_DECREMENT_METRIC: 100.0 * (total / (best * len(values)) - 1.0),
        }[self.metric]
        if _numeric_scalar(self.observation) != expected:
            raise ValueError("RSA result scalar does not reproduce from repetitions")

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def protocol(self) -> RSAProtocolIdentity:
        return self.repetitions[0].protocol


def _calculate_rsa_metric(
    repetitions: tuple[RSARepetitionObservation, ...],
    metric: RegistryReference,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> RSAResult | RefusalResult:
    ids = tuple(
        item.observation.observation_id
        for item in repetitions
        if isinstance(item, RSARepetitionObservation)
    )
    try:
        _validate_repetition_series(repetitions)
        operation, equation = _metric_spec(metric)
        values = tuple(item.time_seconds for item in repetitions)
        best = min(values)
        total = math.fsum(values)
        value = {
            RSA_BEST_TIME_METRIC: best,
            RSA_MEAN_TIME_METRIC: total / len(values),
            RSA_TOTAL_TIME_METRIC: total,
            RSA_PERCENT_DECREMENT_METRIC: 100.0 * (total / (best * len(values)) - 1.0),
        }[metric]
        first = repetitions[0]
        protocol = first.protocol
        source_identity = first.observation.identity
        if not isinstance(source_identity, RSAMeasurementIdentity):
            raise ValueError("RSA output requires RSAMeasurementIdentity")
        source_ids = tuple(item.observation.observation_id for item in repetitions)
        parameters = (
            MetadataEntry("equation", equation),
            MetadataEntry("metric", metric.stable_id),
            MetadataEntry("operation", operation.stable_id),
            MetadataEntry("set_id", first.set_id.qualified),
            MetadataEntry("repetition_count", len(repetitions)),
            MetadataEntry(
                "source_observation_ids", ",".join(item.qualified for item in source_ids)
            ),
        )
        unit = PERCENT if metric == RSA_PERCENT_DECREMENT_METRIC else SECOND
        identity = RSAMeasurementIdentity(
            identity_id=ScientificIdentifier(
                "dynamislm",
                "measurement-identity",
                f"rsa-{metric.identifier.key}:{first.set_id.value}",
                FIELD_TESTING_REGISTRY_VERSION,
            ),
            semantic=FieldTestingSemanticIdentity(
                construct=RSA_CONSTRUCT,
                test_family=RSA_TEST_FAMILY,
                protocol=protocol.reference,
                measurand=RSA_SPRINT_TIME_MEASURAND,
                metric_definition=metric,
                protocol_identity=protocol,
            ),
            acquisition=source_identity.acquisition,
            processing=FieldTestingProcessingIdentity(
                estimator=(
                    RSA_PERCENT_DECREMENT_ESTIMATOR
                    if metric == RSA_PERCENT_DECREMENT_METRIC
                    else None
                ),
                registered_operation=operation,
                method_parameters=parameters,
                unit=unit,
                aggregation=COMPLETE_REGISTERED_REPETITIONS,
                filtering=_protocol_processing_components(protocol)[0],
                filtering_status=_protocol_processing_components(protocol)[1],
                smoothing=_protocol_processing_components(protocol)[2],
                interpolation=_protocol_processing_components(protocol)[3],
                processing_state=FieldTestProcessingState.DYNAMISLM_PROCESSED,
            ),
            version=VersionIdentity(
                processing_method=operation,
                method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
                software_version=FIELD_TESTING_SOFTWARE_VERSION,
                hardware_firmware=source_identity.version.hardware_firmware,
            ),
        )
        source_observations_list: list[ScientificMeasurementObservation] = []
        for repetition in repetitions:
            assert repetition.source_qualification is not None
            source_observations_list.extend(
                (repetition.observation, repetition.source_qualification.qualification_observation)
            )
        source_observations = tuple(source_observations_list)
        output = _build_derived_observation(
            source_observations=source_observations,
            identity=identity,
            value=value,
            unit=unit,
            operation=operation,
            parameters=parameters,
            output_observation_id=output_observation_id,
            extra_source_entities=(first.set_id,),
        )
        return RSAResult(output, metric, repetitions)
    except (AttributeError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            "calculate registered RSA aggregate",
            (RefusalReasonCode.TRIAL_SET_INCOMPLETE, RefusalReasonCode.METRIC_DEFINITION_MISMATCH),
            (str(exc),),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def calculate_rsa_best_time(
    repetitions: tuple[RSARepetitionObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> RSAResult | RefusalResult:
    return _calculate_rsa_metric(
        repetitions, RSA_BEST_TIME_METRIC, output_observation_id=output_observation_id
    )


def calculate_rsa_mean_time(
    repetitions: tuple[RSARepetitionObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> RSAResult | RefusalResult:
    return _calculate_rsa_metric(
        repetitions, RSA_MEAN_TIME_METRIC, output_observation_id=output_observation_id
    )


def calculate_rsa_total_time(
    repetitions: tuple[RSARepetitionObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> RSAResult | RefusalResult:
    return _calculate_rsa_metric(
        repetitions, RSA_TOTAL_TIME_METRIC, output_observation_id=output_observation_id
    )


def calculate_rsa_percent_decrement(
    repetitions: tuple[RSARepetitionObservation, ...],
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> RSAResult | RefusalResult:
    return _calculate_rsa_metric(
        repetitions, RSA_PERCENT_DECREMENT_METRIC, output_observation_id=output_observation_id
    )


def aggregate_rsa(
    repetitions: tuple[RSARepetitionObservation, ...],
) -> tuple[RSAResult | RefusalResult, ...]:
    """Return the four registered RSA summaries for one complete repetition set."""

    return (
        calculate_rsa_best_time(repetitions),
        calculate_rsa_mean_time(repetitions),
        calculate_rsa_total_time(repetitions),
        calculate_rsa_percent_decrement(repetitions),
    )


def refuse_rsa_decrement_as_fatigue(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "interpret RSA percent decrement as physiological fatigue",
        (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
        (
            "physiological, readiness or neuromuscular fatigue evidence and "
            "a registered interpretation",
        ),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=("RSA percent decrement remains a mechanical performance descriptor",),
    )


def refuse_alternate_rsa_decrement(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "use an alternate RSA decrement equation as registered S_dec",
        (RefusalReasonCode.ESTIMATOR_MISMATCH,),
        ("the exact registered total-over-best-times-n equation",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


RSARepetition = RSARepetitionObservation
RSAAggregateResult = RSAResult
calculate_rsa_best = calculate_rsa_best_time
calculate_rsa_mean = calculate_rsa_mean_time
calculate_rsa_total = calculate_rsa_total_time
calculate_rsa_s_dec = calculate_rsa_percent_decrement
RepeatedSprintProtocolIdentity = RSAProtocolIdentity
RepeatedSprintObservation = RSARepetitionObservation


__all__ = [
    "RSAAggregateResult",
    "RSAMovementMode",
    "RSAProtocolIdentity",
    "RSARecoveryMode",
    "RSARepetition",
    "RSARepetitionObservation",
    "RSAResult",
    "RepeatedSprintObservation",
    "RepeatedSprintProtocolIdentity",
    "aggregate_rsa",
    "build_rsa_repetition_observation",
    "calculate_rsa_best",
    "calculate_rsa_best_time",
    "calculate_rsa_mean",
    "calculate_rsa_mean_time",
    "calculate_rsa_percent_decrement",
    "calculate_rsa_s_dec",
    "calculate_rsa_total",
    "calculate_rsa_total_time",
    "qualify_rsa_repetition",
    "refuse_alternate_rsa_decrement",
    "refuse_rsa_decrement_as_fatigue",
    "rsa_6x40m_shuttle_protocol_v1",
]
