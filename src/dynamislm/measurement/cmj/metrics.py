"""Registered RES-65 CMJ force, power, and scalar metric operations.

This module is an additive completion layer over the sealed RES-34--RES-50
CMJ objects.  It never detects a new event, integrates a new velocity, or
turns a display label into a measurement identity.  Every public constructor
accepts the typed upstream result that supplies the quantity being claimed and
recomputes its scalar output from that source where practical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.cmj.events import (
    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
    CMJEventDetectorParameters,
    CMJEventLabel,
    CMJEventOccurrence,
    CMJEventOccurrenceStatus,
)
from dynamislm.measurement.cmj.identity import (
    CMJ_REGISTRY_VERSION,
    CMJ_TEST_FAMILY,
    CMJMeasurementIdentity,
    CMJSemanticIdentity,
)
from dynamislm.measurement.cmj.jump_height import (
    CMJJumpHeightResult,
    JumpHeightEstimatorFamily,
)
from dynamislm.measurement.cmj.mechanics import (
    CMJMechanicalSystemContract,
    QualifiedZeroVelocityReference,
    SupportedSystemComVelocityResult,
)
from dynamislm.measurement.cmj.phases import (
    CMJPhaseBoundary,
    CMJPhaseLabel,
    CMJPhaseOccurrence,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_BRAKING_MEAN_FORCE_ASYMMETRY_METRIC,
    CMJ_BRAKING_MEAN_SIGNED_POWER_METRIC,
    CMJ_BRAKING_PEAK_FORCE_ASYMMETRY_METRIC,
    CMJ_BRAKING_PEAK_NEGATIVE_POWER_METRIC,
    CMJ_BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_FORCE_ASYMMETRY_MEASURAND,
    CMJ_FORCE_ASYMMETRY_SCHEMA,
    CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION,
    CMJ_POWER_SAMPLED_SIGNED_EXTREMUM_OPERATION,
    CMJ_POWER_SERIES_OPERATION,
    CMJ_POWER_SERIES_SCHEMA,
    CMJ_POWER_TIME_WEIGHTED_MEAN_OPERATION,
    CMJ_PROPULSION_MEAN_FORCE_ASYMMETRY_METRIC,
    CMJ_PROPULSION_MEAN_SIGNED_POWER_METRIC,
    CMJ_PROPULSION_PEAK_FORCE_ASYMMETRY_METRIC,
    CMJ_PROPULSION_PEAK_POSITIVE_POWER_METRIC,
    CMJ_PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_RES65_METRIC_COMPARABILITY_RULE,
    CMJ_RES65_SAMPLE_SUPPORT_CONVENTION,
    CMJ_RSI_MOD_FLIGHT_TIME_METRIC,
    CMJ_RSI_MOD_FLIGHT_TIME_OPERATION,
    CMJ_RSI_MOD_MEASURAND,
    CMJ_RSI_MOD_SCHEMA,
    CMJ_RSI_MOD_TAKEOFF_VELOCITY_METRIC,
    CMJ_RSI_MOD_TAKEOFF_VELOCITY_OPERATION,
    CMJ_SAMPLE_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_SUPPORTED_SYSTEM_EXTERNAL_MECHANICAL_POWER_MEASURAND,
    CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
    CMJ_TAKEOFF_VELOCITY_SCALAR_MEASURAND,
    CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC,
    CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION,
    CMJ_TAKEOFF_VELOCITY_SCALAR_SCHEMA,
    CMJ_TIME_WEIGHTED_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
    CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND,
    CMJ_TRAPEZOIDAL_INTEGRATION_METHOD,
    CMJ_WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    METERS_PER_SECOND,
    NEWTON,
    PERCENT,
    RES65_DECISION_CMJ_METRIC_COMPLETION,
    WATT,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    CMJForceInput,
    ProcessedVerticalForceSignal,
    TotalSupportedForceResult,
    _force_semantics_refusal,
    _input_common_refusal,
    _merge_provenance,
    _provenance_with_run,
    construct_total_supported_vertical_force,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    UnitReference,
    VersionIdentity,
    require_tuple,
)
from dynamislm.measurement.observation import (
    ObservationContext,
    ScientificMeasurementObservation,
)
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
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
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import (
    canonical_hash,
    canonical_json,
    from_canonical_json,
    register_serializable_type,
)

RES65_SOFTWARE_VERSION = "dynamislm-res65-1.0.0"
_UNCERTAINTY_NOTE = (
    "RES-65 deterministic metric arithmetic; measurement uncertainty is not assessed."
)


class CMJMetricSupportKind(StrEnum):
    WHOLE_MOVEMENT = "WHOLE_MOVEMENT"
    BRAKING = "BRAKING"
    PROPULSION = "PROPULSION"


class CMJForceMetric(StrEnum):
    WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE = (
        "WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE"
    )
    WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE = (
        "WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE"
    )
    BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE = "BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE"
    BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE = (
        "BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE"
    )
    PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE = (
        "PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE"
    )
    PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE = (
        "PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE"
    )


class CMJPowerMetric(StrEnum):
    BRAKING_PEAK_NEGATIVE_POWER = "BRAKING_PEAK_NEGATIVE_POWER"
    BRAKING_MEAN_SIGNED_POWER = "BRAKING_MEAN_SIGNED_POWER"
    PROPULSION_PEAK_POSITIVE_POWER = "PROPULSION_PEAK_POSITIVE_POWER"
    PROPULSION_MEAN_SIGNED_POWER = "PROPULSION_MEAN_SIGNED_POWER"


class CMJRSIModNumerator(StrEnum):
    FLIGHT_TIME_JUMP_HEIGHT = "FLIGHT_TIME_JUMP_HEIGHT"
    TAKEOFF_VELOCITY_JUMP_HEIGHT = "TAKEOFF_VELOCITY_JUMP_HEIGHT"


class CMJAsymmetryMetric(StrEnum):
    BRAKING_PEAK_FORCE = "BRAKING_PEAK_FORCE"
    BRAKING_TIME_MEAN_FORCE = "BRAKING_TIME_MEAN_FORCE"
    PROPULSION_PEAK_FORCE = "PROPULSION_PEAK_FORCE"
    PROPULSION_TIME_MEAN_FORCE = "PROPULSION_TIME_MEAN_FORCE"


class CMJAsymmetryEquation(StrEnum):
    RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT = "RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJMetricSupport:
    """Exact inclusive source support for one RES-65 metric."""

    kind: CMJMetricSupportKind
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_sample_count: int
    source_timebase: SignalTimebase
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float
    sample_convention: RegistryReference = CMJ_RES65_SAMPLE_SUPPORT_CONVENTION
    phase_occurrence: CMJPhaseOccurrence | None = None
    movement_onset: CMJEventOccurrence | None = None
    takeoff: CMJEventOccurrence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CMJMetricSupportKind):
            raise ValueError("metric support kind must be registered")
        for field_name, value, expected_type in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
        ):
            if value.instance_type != expected_type:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("source_measurement_identity_id must be a measurement identity")
        if type(self.source_sample_count) is not int or self.source_sample_count < 2:
            raise ValueError("metric support requires at least two source samples")
        if not isinstance(self.source_timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("metric support requires a registered source timebase")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("metric support indices must be integers")
        if not 0 <= self.start_index < self.end_index < self.source_sample_count:
            raise ValueError("metric support must be an inclusive non-empty source interval")
        for field_name, numeric_value in (
            ("start_time_s", self.start_time_s),
            ("end_time_s", self.end_time_s),
        ):
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, int | float)
                or not math.isfinite(numeric_value)
            ):
                raise ValueError(f"{field_name} must be finite")
        expected_start = _time_at(self.source_timebase, self.start_index)
        expected_end = _time_at(self.source_timebase, self.end_index)
        if self.start_time_s != expected_start or self.end_time_s != expected_end:
            raise ValueError("metric support times must equal exact source sample times")
        if self.sample_convention.stable_id != CMJ_RES65_SAMPLE_SUPPORT_CONVENTION.stable_id:
            raise ValueError("metric support sample convention is not registered")
        if self.kind is CMJMetricSupportKind.WHOLE_MOVEMENT:
            if (
                self.phase_occurrence is not None
                or self.movement_onset is None
                or self.takeoff is None
            ):
                raise ValueError("whole-movement support requires onset and takeoff only")
            _require_event_source(self.movement_onset, self, CMJEventLabel.MOVEMENT_ONSET)
            _require_event_source(self.takeoff, self, CMJEventLabel.TAKEOFF_CONTACT_LOSS)
            if (
                self.start_index != self.movement_onset.sample_index
                or self.end_index != self.takeoff.sample_index
            ):
                raise ValueError("whole-movement support does not match its event samples")
            if (
                self.start_time_s != self.movement_onset.event_time_s
                or self.end_time_s != self.takeoff.event_time_s
            ):
                raise ValueError("whole-movement support does not match its event times")
        else:
            expected_label = (
                CMJPhaseLabel.BRAKING
                if self.kind is CMJMetricSupportKind.BRAKING
                else CMJPhaseLabel.PROPULSION
            )
            if self.phase_occurrence is None or self.phase_occurrence.label is not expected_label:
                raise ValueError("phase support does not match its registered phase kind")
            if self.movement_onset is not None or self.takeoff is not None:
                raise ValueError("phase support must not contain separate event fields")
            phase = self.phase_occurrence
            if (
                phase.source_observation_id != self.source_observation_id
                or phase.source_signal_id != self.source_signal_id
                or phase.source_artifact_id != self.source_artifact_id
                or phase.source_acquisition_id != self.source_acquisition_id
                or phase.source_measurement_identity.identity_id
                != self.source_measurement_identity_id
                or phase.start_boundary.source_timebase != self.source_timebase
            ):
                raise ValueError("phase support source identity does not match total force")
            if (
                self.start_index != phase.sample_support.start_index
                or self.end_index != phase.sample_support.end_index
            ):
                raise ValueError("phase support does not match its phase occurrence")
            if self.start_time_s != phase.start_time_s or self.end_time_s != phase.end_time_s:
                raise ValueError("phase support does not match its phase occurrence times")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJForceMetricResult:
    """One sampled-peak or time-weighted total-force metric."""

    observation: ScientificMeasurementObservation
    metric: CMJForceMetric
    source_force: TotalSupportedForceResult
    support: CMJMetricSupport

    def __post_init__(self) -> None:
        spec = _force_spec(self.metric)
        _validate_scalar_output(
            self.observation,
            measurand=CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND,
            metric=spec.metric_reference,
            operation=spec.operation,
            unit=NEWTON,
        )
        if self.support.kind is not spec.support_kind:
            raise ValueError("force metric support kind does not match its metric")
        total = _validated_total_force(self.source_force, None, "validate RES-65 force metric")
        if isinstance(total, RefusalResult):
            raise ValueError("force metric source is not a valid total supported force")
        _require_exact_context(
            self.observation.context,
            total.observation.context,
            "force metric output",
        )
        _require_output_source_identity(self.observation, total.observation.identity)
        _validate_support_against_total(self.support, total)
        if self.support.phase_occurrence is not None:
            if _validate_phase_source(total, self.support.phase_occurrence) is not None:
                raise ValueError("force metric phase source is not the exact total force")
        expected = _force_value(total, self.support, spec.statistic)
        _require_result_value(self.observation, expected)
        _require_output_entities(
            self.observation,
            (
                total.observation.observation_id,
                total.signal.signal_id,
                *(
                    event.occurrence_id
                    for event in (self.support.movement_onset, self.support.takeoff)
                    if event is not None
                ),
                *(
                    (self.support.phase_occurrence.occurrence_id,)
                    if self.support.phase_occurrence is not None
                    else ()
                ),
            ),
        )
        parameters = _parameter_map(self.observation.identity)
        _require_parameters(
            parameters,
            {
                "metric": self.metric.value,
                "metric_definition": spec.metric_reference.stable_id,
                "operation_id": spec.operation.stable_id,
                "source_force_observation_id": total.observation.observation_id.qualified,
                "source_force_signal_id": total.signal.signal_id.qualified,
                "support_kind": self.support.kind.value,
                "start_index": self.support.start_index,
                "end_index": self.support.end_index,
                "sample_convention": self.support.sample_convention.stable_id,
            },
        )

    @property
    def value_n(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def method_identity_key(self) -> object:
        spec = _force_spec(self.metric)
        identity = self.source_force.observation.identity
        return {
            "metric": spec.metric_reference,
            "operation": spec.operation,
            "support_kind": self.support.kind,
            "phase_definition": (
                self.support.phase_occurrence.phase_definition
                if self.support.phase_occurrence is not None
                else None
            ),
            "phase_method": (
                _phase_method_identity_key(self.support.phase_occurrence)
                if self.support.phase_occurrence is not None
                else None
            ),
            "movement_onset_method": (
                _event_method_key(self.support.movement_onset)
                if self.support.movement_onset is not None
                else None
            ),
            "takeoff_method": (
                _event_method_key(self.support.takeoff)
                if self.support.takeoff is not None
                else None
            ),
            "sample_convention": self.support.sample_convention,
            "statistic": spec.statistic,
            "timebase": _timebase_method_key(self.support.source_timebase),
            "processing_state": self.source_force.signal.processing_state,
            "filtering": identity.processing.filtering,
            "interpolation": "none",
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPowerSeries:
    """Sample-attached signed external mechanical power for one phase."""

    series_id: InstanceIdentifier
    artifact_id: InstanceIdentifier
    source_force_observation_id: InstanceIdentifier
    source_force_signal_id: InstanceIdentifier
    source_force_artifact_id: InstanceIdentifier
    source_force_acquisition_id: InstanceIdentifier
    source_force_measurement_identity_id: ScientificIdentifier
    source_velocity_observation_id: InstanceIdentifier
    source_velocity_series_id: InstanceIdentifier
    source_velocity_measurement_identity_id: ScientificIdentifier
    source_sample_count: int
    sample_start_index: int
    samples: tuple[float, ...]
    timebase: SignalTimebase
    unit: UnitReference
    operation: RegistryReference
    system_contract: CMJMechanicalSystemContract
    phase_occurrence: CMJPhaseOccurrence
    sign_convention: SignConvention

    def __post_init__(self) -> None:
        if self.series_id.instance_type != "signal" or self.artifact_id.instance_type != "artifact":
            raise ValueError("power series identifiers have the wrong type")
        for field_name, value, expected_type in (
            ("source_force_observation_id", self.source_force_observation_id, "observation"),
            ("source_force_signal_id", self.source_force_signal_id, "signal"),
            ("source_force_artifact_id", self.source_force_artifact_id, "artifact"),
            ("source_force_acquisition_id", self.source_force_acquisition_id, "acquisition"),
            ("source_velocity_observation_id", self.source_velocity_observation_id, "observation"),
            ("source_velocity_series_id", self.source_velocity_series_id, "signal"),
        ):
            if value.instance_type != expected_type:
                raise ValueError(f"{field_name} has the wrong identifier type")
        for field_name, identity_id in (
            ("source_force_measurement_identity_id", self.source_force_measurement_identity_id),
            (
                "source_velocity_measurement_identity_id",
                self.source_velocity_measurement_identity_id,
            ),
        ):
            if identity_id.object_type != "measurement-identity":
                raise ValueError(f"{field_name} must identify a measurement identity")
        require_tuple(self.samples, "samples")
        if type(self.source_sample_count) is not int or self.source_sample_count < 2:
            raise ValueError("power series source support must contain at least two samples")
        if type(self.sample_start_index) is not int or self.sample_start_index < 0:
            raise ValueError("power series sample_start_index must be nonnegative")
        if self.sample_start_index + len(self.samples) > self.source_sample_count:
            raise ValueError("power series exceeds source sample support")
        if not self.samples:
            raise ValueError("power series must contain samples")
        for sample in self.samples:
            _finite(sample, "power sample")
        if not isinstance(self.timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("power series requires a registered timebase")
        if self.unit.identifier.stable_id != WATT.identifier.stable_id:
            raise ValueError("power series requires watts")
        if self.operation.stable_id != CMJ_POWER_SERIES_OPERATION.stable_id:
            raise ValueError("power series operation is not registered")
        if not self.system_contract.is_authorized:
            raise ValueError("power series requires an authorized system contract")
        phase = self.phase_occurrence
        if (
            phase.start_boundary.source_timebase != self.timebase
            or phase.sample_support.start_index != self.sample_start_index
            or len(self.samples)
            != phase.sample_support.end_index - phase.sample_support.start_index + 1
            or phase.source_velocity_series_id != self.source_velocity_series_id
            or phase.source_velocity_observation_id != self.source_velocity_observation_id
        ):
            raise ValueError("power series does not preserve exact phase/velocity support")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPowerResult:
    """One signed peak or time-weighted phase power metric."""

    observation: ScientificMeasurementObservation
    metric: CMJPowerMetric
    source_force: TotalSupportedForceResult
    source_velocity: SupportedSystemComVelocityResult
    phase_occurrence: CMJPhaseOccurrence
    series: CMJPowerSeries

    def __post_init__(self) -> None:
        spec = _power_spec(self.metric)
        _validate_scalar_output(
            self.observation,
            measurand=CMJ_SUPPORTED_SYSTEM_EXTERNAL_MECHANICAL_POWER_MEASURAND,
            metric=spec.metric_reference,
            operation=spec.operation,
            unit=WATT,
        )
        if self.phase_occurrence.label is not spec.phase_label:
            raise ValueError("power metric phase does not match its metric")
        total = _validated_total_force(self.source_force, None, "validate RES-65 power metric")
        if isinstance(total, RefusalResult):
            raise ValueError("power source is not a valid total supported force")
        if not isinstance(self.source_velocity, SupportedSystemComVelocityResult):
            raise ValueError("power result requires a supported-system COM velocity result")
        _require_exact_context(
            self.observation.context,
            total.observation.context,
            "power output and force source",
        )
        _require_exact_context(
            self.observation.context,
            self.source_velocity.observation.context,
            "power output and velocity source",
        )
        _require_exact_context(
            self.observation.context,
            self.phase_occurrence.source_context,
            "power output and phase source",
        )
        _require_output_source_identity(self.observation, self.source_velocity.observation.identity)
        binding = _validate_power_binding(total, self.source_velocity, self.phase_occurrence)
        if isinstance(binding, RefusalResult):
            raise ValueError("power source force/velocity/phase binding is invalid")
        expected_samples = _power_samples(total, self.source_velocity, self.phase_occurrence)
        if self.series.samples != expected_samples:
            raise ValueError("power series values do not match exact force and velocity sources")
        if self.series.phase_occurrence != self.phase_occurrence:
            raise ValueError("power series phase does not match power result")
        if (
            self.series.source_force_observation_id != total.observation.observation_id
            or self.series.source_force_signal_id != total.signal.signal_id
            or self.series.source_force_artifact_id != total.source_artifact.artifact_id
            or self.series.source_force_acquisition_id != total.acquisition.acquisition_id
            or self.series.source_force_measurement_identity_id
            != total.observation.identity.identity_id
            or self.series.source_velocity_observation_id
            != self.source_velocity.observation.observation_id
            or self.series.source_velocity_series_id != self.source_velocity.series.series_id
            or self.series.source_velocity_measurement_identity_id
            != self.source_velocity.observation.identity.identity_id
            or self.series.timebase != _required_signal_timebase(total.signal)
            or self.series.system_contract != self.source_velocity.system_contract
            or self.series.sign_convention != _required_signal_sign(total.signal)
        ):
            raise ValueError("power series source metadata does not match exact inputs")
        expected = _power_value(
            expected_samples,
            self.phase_occurrence,
            _required_signal_timebase(total.signal),
            spec.statistic,
        )
        _require_result_value(self.observation, expected)
        _require_output_entities(
            self.observation,
            (
                total.observation.observation_id,
                total.signal.signal_id,
                self.source_velocity.observation.observation_id,
                self.source_velocity.series.series_id,
                self.phase_occurrence.occurrence_id,
            ),
        )
        parameters = _parameter_map(self.observation.identity)
        _require_parameters(
            parameters,
            {
                "metric": self.metric.value,
                "metric_definition": spec.metric_reference.stable_id,
                "operation_id": spec.operation.stable_id,
                "power_force_identity": "TOTAL_SUPPORTED_VERTICAL_FORCE",
                "power_velocity_identity": "SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY",
                "power_series_id": self.series.series_id.qualified,
                "phase_occurrence_id": self.phase_occurrence.occurrence_id.qualified,
            },
        )

    @property
    def value_w(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def method_identity_key(self) -> object:
        spec = _power_spec(self.metric)
        return {
            "metric": spec.metric_reference,
            "operation": spec.operation,
            "power_series_operation": CMJ_POWER_SERIES_OPERATION,
            "force_quantity": "TOTAL_SUPPORTED_VERTICAL_FORCE",
            "velocity_quantity": "SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY",
            "phase_system": self.phase_occurrence.phase_system,
            "phase_definition": self.phase_occurrence.phase_definition,
            "phase_method": _phase_method_identity_key(self.phase_occurrence),
            "timebase": _timebase_method_key(self.phase_occurrence.start_boundary.source_timebase),
            "system_contract": self.source_velocity.system_contract,
            "statistic": spec.statistic,
            "filtering": self.source_velocity.observation.identity.processing.filtering,
            "interpolation": "none",
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJTakeoffVelocityResult:
    """Exact scalar projection of the sealed supported-system COM velocity."""

    observation: ScientificMeasurementObservation
    source_velocity: SupportedSystemComVelocityResult
    takeoff_event: CMJEventOccurrence

    def __post_init__(self) -> None:
        _validate_scalar_output(
            self.observation,
            measurand=CMJ_TAKEOFF_VELOCITY_SCALAR_MEASURAND,
            metric=CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC,
            operation=CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION,
            unit=METERS_PER_SECOND,
        )
        if not isinstance(self.source_velocity, SupportedSystemComVelocityResult):
            raise ValueError("takeoff velocity result requires a supported-system velocity result")
        if not isinstance(self.takeoff_event, CMJEventOccurrence):
            raise ValueError("takeoff velocity result requires a CMJ takeoff event")
        _require_exact_context(
            self.observation.context,
            self.source_velocity.observation.context,
            "takeoff velocity output",
        )
        _require_output_source_identity(self.observation, self.source_velocity.observation.identity)
        binding = _validate_takeoff_velocity_binding(self.source_velocity, self.takeoff_event)
        if isinstance(binding, RefusalResult):
            raise ValueError("takeoff velocity source/event binding is invalid")
        value = _takeoff_velocity_value(self.source_velocity, self.takeoff_event)
        _require_result_value(self.observation, value)
        _require_output_entities(
            self.observation,
            (
                self.source_velocity.observation.observation_id,
                self.source_velocity.series.series_id,
                self.takeoff_event.occurrence_id,
            ),
        )
        parameters = _parameter_map(self.observation.identity)
        _require_parameters(
            parameters,
            {
                "metric_definition": CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC.stable_id,
                "operation_id": CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION.stable_id,
                "schema": CMJ_TAKEOFF_VELOCITY_SCALAR_SCHEMA.stable_id,
                "sample_convention": CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION.stable_id,
                "source_velocity_observation_id": (
                    self.source_velocity.observation.observation_id.qualified
                ),
                "source_velocity_series_id": self.source_velocity.series.series_id.qualified,
                "takeoff_event_id": self.takeoff_event.occurrence_id.qualified,
            },
        )

    @property
    def value_m_per_s(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def method_identity_key(self) -> object:
        condition = self.source_velocity.initial_velocity_condition
        return {
            "metric": CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC,
            "operation": CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION,
            "sample_convention": CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
            "velocity_operation": self.source_velocity.series.operation,
            "velocity_integration_method": self.source_velocity.series.integration_method,
            "zero_velocity_method": condition.method
            if isinstance(condition, QualifiedZeroVelocityReference)
            else None,
            "zero_velocity_evidence": condition.evidence_decision
            if isinstance(condition, QualifiedZeroVelocityReference)
            else None,
            "system_contract": self.source_velocity.system_contract,
            "takeoff_method": _event_method_key(self.takeoff_event),
            "timebase": _timebase_method_key(self.source_velocity.series.timebase),
            "filtering": self.source_velocity.observation.identity.processing.filtering,
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJRSIModResult:
    """Estimator-specific RSI-modified ratio bound to JH and RES-36 events."""

    observation: ScientificMeasurementObservation
    jump_height: CMJJumpHeightResult
    movement_onset: CMJEventOccurrence
    takeoff_event: CMJEventOccurrence
    numerator: CMJRSIModNumerator

    def __post_init__(self) -> None:
        metric, operation = _rsi_spec(self.numerator)
        _validate_scalar_output(
            self.observation,
            measurand=CMJ_RSI_MOD_MEASURAND,
            metric=metric,
            operation=operation,
            unit=METERS_PER_SECOND,
            value_origin=ValueOrigin.MODEL_ESTIMATE,
        )
        if not isinstance(self.jump_height, CMJJumpHeightResult):
            raise ValueError("RSI-mod result requires a CMJ jump-height result")
        if not isinstance(self.movement_onset, CMJEventOccurrence) or not isinstance(
            self.takeoff_event, CMJEventOccurrence
        ):
            raise ValueError("RSI-mod result requires CMJ onset and takeoff events")
        _require_exact_context(
            self.observation.context,
            self.jump_height.observation.context,
            "RSI-mod output",
        )
        _require_output_source_identity(self.observation, self.jump_height.observation.identity)
        binding = _validate_rsi_binding(
            self.jump_height, self.movement_onset, self.takeoff_event, self.numerator
        )
        if isinstance(binding, RefusalResult):
            raise ValueError("RSI-mod source/event binding is invalid")
        value = self.jump_height.value_m / (
            self.takeoff_event.event_time_s - self.movement_onset.event_time_s
        )
        _require_result_value(self.observation, value)
        _require_output_entities(
            self.observation,
            (
                self.jump_height.observation.observation_id,
                self.movement_onset.occurrence_id,
                self.takeoff_event.occurrence_id,
            ),
        )
        parameters = _parameter_map(self.observation.identity)
        _require_parameters(
            parameters,
            {
                "metric_definition": metric.stable_id,
                "operation_id": operation.stable_id,
                "schema": CMJ_RSI_MOD_SCHEMA.stable_id,
                "numerator": self.numerator.value,
                "jump_height_observation_id": self.jump_height.observation.observation_id.qualified,
                "jump_height_estimator": self.jump_height.method.reference.stable_id,
                "movement_onset_event_id": self.movement_onset.occurrence_id.qualified,
                "takeoff_event_id": self.takeoff_event.occurrence_id.qualified,
                "denominator_semantics": "takeoff_event_time_s - movement_onset_event_time_s",
            },
        )

    @property
    def value_m_per_s(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def time_to_takeoff_s(self) -> float:
        return self.takeoff_event.event_time_s - self.movement_onset.event_time_s

    @property
    def method_identity_key(self) -> object:
        metric, operation = _rsi_spec(self.numerator)
        return {
            "metric": metric,
            "operation": operation,
            "numerator": self.numerator,
            "jump_height_estimator": self.jump_height.method.reference,
            "jump_height_operation": self.jump_height.method.operation,
            "jump_height_gravity": self.jump_height.parameters.gravity,
            "jump_height_source_velocity_operation": (
                self.jump_height.parameters.source_velocity_operation
            ),
            "jump_height_source_velocity_integration_method": (
                self.jump_height.parameters.source_velocity_integration_method
            ),
            "jump_height_source_velocity_initial_condition": (
                _zero_velocity_method_key(
                    self.jump_height.parameters.source_velocity_initial_condition
                )
                if self.jump_height.parameters.source_velocity_initial_condition is not None
                else None
            ),
            "jump_height_system_contract": self.jump_height.parameters.system_contract,
            "jump_height_source_velocity_filtering": (
                self.jump_height.source_velocity.observation.identity.processing.filtering
                if self.jump_height.source_velocity is not None
                else None
            ),
            "movement_onset_method": _event_method_key(self.movement_onset),
            "takeoff_method": _event_method_key(self.takeoff_event),
            "timebase": _timebase_method_key(self.takeoff_event.source_timebase),
            "source_filtering": self.jump_height.observation.identity.processing.filtering,
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJForceAsymmetryResult:
    """Direction-bearing phase force asymmetry from exact bilateral sources."""

    observation: ScientificMeasurementObservation
    metric: CMJAsymmetryMetric
    equation: CMJAsymmetryEquation
    left_source: CMJForceInput
    right_source: CMJForceInput
    total_force: TotalSupportedForceResult
    phase_occurrence: CMJPhaseOccurrence
    left_value_n: float
    right_value_n: float

    def __post_init__(self) -> None:
        spec = _asymmetry_spec(self.metric)
        _validate_scalar_output(
            self.observation,
            measurand=CMJ_FORCE_ASYMMETRY_MEASURAND,
            metric=spec.metric_reference,
            operation=CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION,
            unit=PERCENT,
        )
        if self.phase_occurrence.label is not spec.phase_label:
            raise ValueError("asymmetry metric phase does not match its metric")
        if self.equation is not CMJAsymmetryEquation.RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT:
            raise ValueError("asymmetry equation is not registered")
        resolved = _resolve_bilateral_total(
            self.left_source, self.right_source, self.total_force, "validate RES-65 asymmetry"
        )
        if isinstance(resolved, RefusalResult):
            raise ValueError("asymmetry bilateral source binding is invalid")
        total = resolved
        _require_exact_context(
            self.observation.context,
            self.left_source.observation.context,
            "asymmetry output and left source",
        )
        _require_exact_context(
            self.observation.context,
            self.right_source.observation.context,
            "asymmetry output and right source",
        )
        _require_exact_context(
            self.observation.context,
            total.observation.context,
            "asymmetry output and total-force source",
        )
        _require_exact_context(
            self.observation.context,
            self.phase_occurrence.source_context,
            "asymmetry output and phase source",
        )
        _require_output_source_identity(self.observation, total.observation.identity)
        source_refusal = _validate_phase_source(total, self.phase_occurrence)
        if source_refusal is not None:
            raise ValueError("asymmetry phase source is not the exact bilateral total")
        left_value, right_value = _asymmetry_values(
            self.left_source, self.right_source, self.phase_occurrence, spec.statistic
        )
        if self.left_value_n != left_value or self.right_value_n != right_value:
            raise ValueError("asymmetry limb values do not match exact source samples")
        expected = _asymmetry_value(left_value, right_value, self.equation)
        _require_result_value(self.observation, expected)
        _require_output_entities(
            self.observation,
            (
                self.left_source.observation.observation_id,
                self.right_source.observation.observation_id,
                self.left_source.signal.signal_id,
                self.right_source.signal.signal_id,
                total.observation.observation_id,
                total.signal.signal_id,
                self.phase_occurrence.occurrence_id,
            ),
        )
        parameters = _parameter_map(self.observation.identity)
        _require_parameters(
            parameters,
            {
                "metric_definition": spec.metric_reference.stable_id,
                "operation_id": CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION.stable_id,
                "schema": CMJ_FORCE_ASYMMETRY_SCHEMA.stable_id,
                "equation": self.equation.value,
                "left_source_observation_id": self.left_source.observation.observation_id.qualified,
                "right_source_observation_id": (
                    self.right_source.observation.observation_id.qualified
                ),
                "phase_occurrence_id": self.phase_occurrence.occurrence_id.qualified,
                "numerator_order": "right_minus_left",
                "denominator": "left_value",
            },
        )

    @property
    def value_percent(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def method_identity_key(self) -> object:
        spec = _asymmetry_spec(self.metric)
        left_channel = self.left_source.identity.acquisition.channel
        right_channel = self.right_source.identity.acquisition.channel
        return {
            "metric": spec.metric_reference,
            "operation": CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION,
            "equation": self.equation,
            "phase_system": self.phase_occurrence.phase_system,
            "phase_definition": self.phase_occurrence.phase_definition,
            "phase_method": _phase_method_identity_key(self.phase_occurrence),
            "statistic": spec.statistic,
            "left_role": left_channel.role if left_channel is not None else None,
            "right_role": right_channel.role if right_channel is not None else None,
            "left_device": self.left_source.identity.acquisition.device,
            "right_device": self.right_source.identity.acquisition.device,
            "left_measuring_system": self.left_source.identity.acquisition.measuring_system,
            "right_measuring_system": self.right_source.identity.acquisition.measuring_system,
            "left_sampling": self.left_source.identity.acquisition.sampling,
            "right_sampling": self.right_source.identity.acquisition.sampling,
            "left_processing_state": self.left_source.signal.processing_state,
            "right_processing_state": self.right_source.signal.processing_state,
            "acquisition_software_version": (
                self.left_source.identity.acquisition.acquisition_software_version
            ),
            "timebase": _timebase_method_key(self.phase_occurrence.start_boundary.source_timebase),
            "filtering": self.left_source.identity.processing.filtering,
            "interpolation": "none",
        }


type CMJCompletedMetricResult = (
    CMJForceMetricResult
    | CMJPowerResult
    | CMJTakeoffVelocityResult
    | CMJRSIModResult
    | CMJForceAsymmetryResult
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJMetricComparabilityRequest:
    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("request_id must identify a comparability request")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("metric comparability requires distinct observations")
        if not self.claim.strip():
            raise ValueError("metric comparability claim must not be empty")
        require_tuple(self.requested_transformations, "requested_transformations")


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    metric_reference: RegistryReference
    operation: RegistryReference
    support_kind: CMJMetricSupportKind
    statistic: str


@dataclass(frozen=True, slots=True)
class _PowerSpec:
    metric_reference: RegistryReference
    operation: RegistryReference
    phase_label: CMJPhaseLabel
    statistic: str
    sign_requirement: str


@dataclass(frozen=True, slots=True)
class _AsymmetrySpec:
    metric_reference: RegistryReference
    phase_label: CMJPhaseLabel
    statistic: str


_FORCE_SPECS: dict[CMJForceMetric, _MetricSpec] = {
    CMJForceMetric.WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_SAMPLE_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.WHOLE_MOVEMENT,
        "SAMPLE_MAXIMUM",
    ),
    CMJForceMetric.WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_TIME_WEIGHTED_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.WHOLE_MOVEMENT,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
    ),
    CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_SAMPLE_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.BRAKING,
        "SAMPLE_MAXIMUM",
    ),
    CMJForceMetric.BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_TIME_WEIGHTED_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.BRAKING,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
    ),
    CMJForceMetric.PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_SAMPLE_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.PROPULSION,
        "SAMPLE_MAXIMUM",
    ),
    CMJForceMetric.PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE: _MetricSpec(
        CMJ_PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        CMJ_TIME_WEIGHTED_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE_OPERATION,
        CMJMetricSupportKind.PROPULSION,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
    ),
}
_POWER_SPECS: dict[CMJPowerMetric, _PowerSpec] = {
    CMJPowerMetric.BRAKING_PEAK_NEGATIVE_POWER: _PowerSpec(
        CMJ_BRAKING_PEAK_NEGATIVE_POWER_METRIC,
        CMJ_POWER_SAMPLED_SIGNED_EXTREMUM_OPERATION,
        CMJPhaseLabel.BRAKING,
        "SAMPLED_MINIMUM",
        "NEGATIVE",
    ),
    CMJPowerMetric.BRAKING_MEAN_SIGNED_POWER: _PowerSpec(
        CMJ_BRAKING_MEAN_SIGNED_POWER_METRIC,
        CMJ_POWER_TIME_WEIGHTED_MEAN_OPERATION,
        CMJPhaseLabel.BRAKING,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
        "SIGNED",
    ),
    CMJPowerMetric.PROPULSION_PEAK_POSITIVE_POWER: _PowerSpec(
        CMJ_PROPULSION_PEAK_POSITIVE_POWER_METRIC,
        CMJ_POWER_SAMPLED_SIGNED_EXTREMUM_OPERATION,
        CMJPhaseLabel.PROPULSION,
        "SAMPLED_MAXIMUM",
        "POSITIVE",
    ),
    CMJPowerMetric.PROPULSION_MEAN_SIGNED_POWER: _PowerSpec(
        CMJ_PROPULSION_MEAN_SIGNED_POWER_METRIC,
        CMJ_POWER_TIME_WEIGHTED_MEAN_OPERATION,
        CMJPhaseLabel.PROPULSION,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
        "SIGNED",
    ),
}
_ASYMMETRY_SPECS: dict[CMJAsymmetryMetric, _AsymmetrySpec] = {
    CMJAsymmetryMetric.BRAKING_PEAK_FORCE: _AsymmetrySpec(
        CMJ_BRAKING_PEAK_FORCE_ASYMMETRY_METRIC, CMJPhaseLabel.BRAKING, "SAMPLE_MAXIMUM"
    ),
    CMJAsymmetryMetric.BRAKING_TIME_MEAN_FORCE: _AsymmetrySpec(
        CMJ_BRAKING_MEAN_FORCE_ASYMMETRY_METRIC,
        CMJPhaseLabel.BRAKING,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
    ),
    CMJAsymmetryMetric.PROPULSION_PEAK_FORCE: _AsymmetrySpec(
        CMJ_PROPULSION_PEAK_FORCE_ASYMMETRY_METRIC, CMJPhaseLabel.PROPULSION, "SAMPLE_MAXIMUM"
    ),
    CMJAsymmetryMetric.PROPULSION_TIME_MEAN_FORCE: _AsymmetrySpec(
        CMJ_PROPULSION_MEAN_FORCE_ASYMMETRY_METRIC,
        CMJPhaseLabel.PROPULSION,
        "TIME_WEIGHTED_TRAPEZOIDAL_MEAN",
    ),
}


def _finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _numeric_scalar(observation: ScientificMeasurementObservation) -> float:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        raise ValueError("metric observation must contain a numeric scalar")
    if not isinstance(value.value, int | float) or not math.isfinite(float(value.value)):
        raise ValueError("metric scalar must be finite")
    return float(value.value)


def _parameter_map(identity: object) -> dict[str, object]:
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("metric observation requires a CMJ measurement identity")
    return {entry.key: entry.value for entry in identity.processing.method_parameters}


def _require_parameters(parameters: dict[str, object], expected: dict[str, object]) -> None:
    for key, value in expected.items():
        if parameters.get(key) != value:
            raise ValueError(f"metric parameter {key} does not preserve its source identity")


def _time_at(timebase: SignalTimebase, index: int) -> float:
    if isinstance(timebase, RegularTimebase):
        return timebase.start_time_s + index / timebase.sample_rate_hz
    if isinstance(timebase, ExplicitTimebase):
        return timebase.times_s[index]
    raise ValueError("registered timebase required")


def _required_signal_timebase(signal: object) -> SignalTimebase:
    timebase = getattr(signal, "timebase", None)
    if not isinstance(timebase, RegularTimebase | ExplicitTimebase):
        raise ValueError("registered source signal timebase required")
    return timebase


def _required_signal_sign(signal: object) -> SignConvention:
    sign = getattr(signal, "sign_convention", None)
    if not isinstance(sign, SignConvention):
        raise ValueError("registered source signal sign convention required")
    return sign


def _timebase_method_key(timebase: SignalTimebase) -> tuple[object, ...]:
    if isinstance(timebase, RegularTimebase):
        return ("REGULAR", timebase.sample_rate_hz)
    return ("EXPLICIT",)


def _event_method_key(event: CMJEventOccurrence) -> object:
    parameters = event.detector_parameters
    return {
        "definition": event.definition.reference,
        "method": event.detector_method.reference,
        "threshold_family": event.detector_method.threshold_family,
        "threshold_n": parameters.threshold_n,
        "sigma_multiplier": parameters.sigma_multiplier,
        "baseline_selection_method": (
            parameters.baseline_segment.selection_method
            if parameters.baseline_segment is not None
            else None
        ),
        "baseline_selection_parameters": (
            tuple(parameters.baseline_segment.selection_parameters)
            if parameters.baseline_segment is not None
            else None
        ),
        "direction": parameters.direction,
        "dwell_samples": parameters.dwell_samples,
        "search_start_index": parameters.search_start_index,
        "timebase": _timebase_method_key(event.source_timebase),
    }


def _detector_method_key(parameters: CMJEventDetectorParameters | None) -> object:
    if parameters is None:
        return None
    baseline_segment = parameters.baseline_segment
    return (
        parameters.threshold_n,
        baseline_segment.selection_method.stable_id if baseline_segment is not None else None,
        (
            tuple((entry.key, entry.value) for entry in baseline_segment.selection_parameters)
            if baseline_segment is not None
            else None
        ),
        parameters.sigma_multiplier,
        parameters.direction,
        parameters.dwell_samples,
        parameters.search_start_index,
    )


def _boundary_method_key(boundary: CMJPhaseBoundary) -> object:
    parameters = getattr(boundary, "source_event_parameters", None)
    parsed: CMJEventDetectorParameters | None = None
    if isinstance(parameters, str):
        try:
            decoded = from_canonical_json(parameters, CMJEventDetectorParameters)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, CMJEventDetectorParameters):
            parsed = decoded
    return (
        getattr(getattr(boundary, "kind", None), "value", None),
        getattr(boundary, "method", None),
        getattr(boundary, "source_event_definition", None),
        getattr(boundary, "source_event_method", None),
        _detector_method_key(parsed),
        getattr(boundary, "tie_policy", None),
        getattr(boundary, "velocity_threshold_policy", None),
        getattr(boundary, "interpolation_policy", None),
        _timebase_method_key(boundary.source_timebase),
    )


def _processing_method_parameters_key(
    parameters: tuple[MetadataEntry, ...],
) -> tuple[tuple[str, object], ...]:
    ignored_keys = {
        "source_signal_id",
        "source_signal_ids",
        "source_observation_id",
        "source_observation_ids",
        "source_artifact_id",
        "source_artifact_ids",
        "source_acquisition_id",
        "source_acquisition_ids",
        "source_measurement_identity_id",
        "source_measurement_identity_ids",
        "source_event_id",
        "source_event_ids",
        "event_id",
        "event_ids",
        "source_sample_count",
        "sample_index",
        "sample_indices",
        "sample_start_index",
        "sample_end_index",
        "search_start_index",
        "search_end_index",
        "start_index",
        "end_index",
        "event_time_s",
        "start_time_s",
        "end_time_s",
        "timestamp",
        "source_timebase",
        "integration_interval",
        "zero_velocity_reference",
        "initial_velocity_condition",
        "displacement_origin",
    }
    ignored_suffixes = (
        "_observation_id",
        "_signal_id",
        "_artifact_id",
        "_acquisition_id",
        "_identity_id",
        "_series_id",
        "_event_id",
        "_event_ids",
        "_occurrence_id",
        "_sample_index",
        "_start_index",
        "_end_index",
        "_time_s",
        "_timestamp",
        "_segment",
        "_qc",
        "_quality_flags",
    )
    return tuple(
        (entry.key, entry.value)
        for entry in parameters
        if entry.key not in ignored_keys and not entry.key.endswith(ignored_suffixes)
    )


def _zero_velocity_method_key(reference: QualifiedZeroVelocityReference) -> object:
    segment = reference.weighing_segment
    return (
        reference.method,
        reference.evidence_decision,
        reference.unit,
        segment.selection_method,
        tuple(segment.selection_parameters),
        reference.weighing_qc.acceptability_adjudicated,
    )


def _phase_method_identity_key(phase: CMJPhaseOccurrence) -> object:
    return {
        "phase_system": phase.phase_system,
        "phase_definition": phase.phase_definition,
        "boundary_convention": phase.boundary_convention,
        "start_boundary": _boundary_method_key(phase.start_boundary),
        "end_boundary": _boundary_method_key(phase.end_boundary),
        "event_methods": _phase_event_method_keys(phase.provenance),
        "velocity_operation": phase.source_velocity_operation,
        "velocity_integration_method": phase.source_velocity_integration_method,
        "velocity_integration": (
            phase.source_velocity_integration_interval.kind,
            phase.source_velocity_integration_interval.boundary_convention,
            phase.source_velocity_integration_interval.integration_method,
        ),
        "zero_velocity_reference": _zero_velocity_method_key(
            phase.source_velocity_initial_condition
        ),
        "velocity_version": phase.source_velocity_version,
        "velocity_filtering": phase.source_velocity_filtering,
        "velocity_processing": _processing_method_parameters_key(
            phase.source_velocity_processing_parameters
        ),
        "system_contract": phase.source_system_contract,
        "timebase": _timebase_method_key(phase.start_boundary.source_timebase),
    }


def _phase_event_method_keys(provenance: Provenance) -> tuple[object, ...]:
    keys: set[tuple[object, ...]] = set()
    for run in provenance.processing_runs:
        if run.method.identifier.object_type != "event-method":
            continue
        parameters = {entry.key: entry.value for entry in run.parameters}
        detector_parameters = parameters.get("detector_parameters")
        parsed: CMJEventDetectorParameters | None = None
        if isinstance(detector_parameters, str):
            try:
                decoded = from_canonical_json(detector_parameters, CMJEventDetectorParameters)
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, CMJEventDetectorParameters):
                parsed = decoded
        keys.add(
            (
                parameters.get("event_definition"),
                run.method,
                _detector_method_key(parsed),
            )
        )
    return tuple(sorted(keys, key=repr))


def _metric_refusal(
    claim: str,
    reasons: tuple[RefusalReasonCode, ...],
    missing: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    reason_values = tuple(reason.value for reason in reasons)
    digest = canonical_hash(
        {
            "claim": claim,
            "reasons": reason_values,
            "missing": missing,
            "observations": observation_ids,
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res65:{digest}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=reason_values,
        missing_information=missing,
        what_can_still_be_safely_described=(
            "the independently valid upstream CMJ observations remain describable",
            "no unsupported CMJ performance or physiological claim is emitted",
        ),
        evidence_references=(RES65_DECISION_CMJ_METRIC_COMPLETION,),
        observation_ids=observation_ids,
    )


def _force_spec(metric: CMJForceMetric) -> _MetricSpec:
    try:
        return _FORCE_SPECS[metric]
    except (KeyError, TypeError):
        raise ValueError("force metric is not registered") from None


def _power_spec(metric: CMJPowerMetric) -> _PowerSpec:
    try:
        return _POWER_SPECS[metric]
    except (KeyError, TypeError):
        raise ValueError("power metric is not registered") from None


def _asymmetry_spec(metric: CMJAsymmetryMetric) -> _AsymmetrySpec:
    try:
        return _ASYMMETRY_SPECS[metric]
    except (KeyError, TypeError):
        raise ValueError("asymmetry metric is not registered") from None


def _rsi_spec(numerator: CMJRSIModNumerator) -> tuple[RegistryReference, RegistryReference]:
    if numerator is CMJRSIModNumerator.FLIGHT_TIME_JUMP_HEIGHT:
        return CMJ_RSI_MOD_FLIGHT_TIME_METRIC, CMJ_RSI_MOD_FLIGHT_TIME_OPERATION
    if numerator is CMJRSIModNumerator.TAKEOFF_VELOCITY_JUMP_HEIGHT:
        return CMJ_RSI_MOD_TAKEOFF_VELOCITY_METRIC, CMJ_RSI_MOD_TAKEOFF_VELOCITY_OPERATION
    raise ValueError("RSI-mod numerator is not registered")


def _validated_total_force(
    force: CMJForceInput | TotalSupportedForceResult,
    counterpart: CMJForceInput | None,
    claim: str,
) -> TotalSupportedForceResult | RefusalResult:
    if isinstance(force, TotalSupportedForceResult):
        if counterpart is not None:
            return _metric_refusal(
                claim,
                (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
                ("counterpart must be absent when a total-force result is supplied",),
                (force.observation.observation_id,),
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
        total = force
    elif isinstance(force, CMJForceInput):
        constructed = construct_total_supported_vertical_force(force, counterpart)
        if isinstance(constructed, RefusalResult):
            return constructed
        total = constructed
    else:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("CMJForceInput or TotalSupportedForceResult",),
        )
    try:
        force_input = total.as_force_input()
    except (TypeError, ValueError):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("typed total supported-force source linkage",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_refusal = _input_common_refusal(force_input, claim)
    if source_refusal is not None:
        return source_refusal
    semantics_refusal = _force_semantics_refusal(force_input, claim)
    if semantics_refusal is not None:
        return semantics_refusal
    return total


def _require_event_source(
    event: CMJEventOccurrence,
    support: CMJMetricSupport,
    expected_label: CMJEventLabel,
) -> None:
    if event.definition.label is not expected_label:
        raise ValueError("metric event has the wrong definition")
    expected_method = (
        CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD
        if expected_label is CMJEventLabel.MOVEMENT_ONSET
        else CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD
    )
    if (
        event.detector_method != expected_method
        or event.status is not CMJEventOccurrenceStatus.DETECTED
    ):
        raise ValueError("metric event method is not the registered RES-36 method")
    if (
        event.source_observation_id != support.source_observation_id
        or event.source_signal_id != support.source_signal_id
        or event.source_artifact_id != support.source_artifact_id
        or event.source_acquisition_id != support.source_acquisition_id
        or event.source_measurement_identity.identity_id != support.source_measurement_identity_id
        or event.source_timebase != support.source_timebase
        or event.source_sample_count != support.source_sample_count
    ):
        raise ValueError("metric event source does not match total force")


def _validate_support_against_total(
    support: CMJMetricSupport,
    total: TotalSupportedForceResult,
) -> None:
    if (
        support.source_observation_id != total.observation.observation_id
        or support.source_signal_id != total.signal.signal_id
        or support.source_artifact_id != total.source_artifact.artifact_id
        or support.source_acquisition_id != total.acquisition.acquisition_id
        or support.source_measurement_identity_id != total.observation.identity.identity_id
        or support.source_sample_count != len(total.signal.samples)
        or support.source_timebase != total.signal.timebase
    ):
        raise ValueError("metric support is not attached to the exact total-force source")


_MISSING_PHASE_PARAMETER = object()


def _processing_run_parameter(run: ProcessingRun, key: str) -> object:
    values = tuple(entry.value for entry in run.parameters if entry.key == key)
    return values[0] if len(values) == 1 else _MISSING_PHASE_PARAMETER


def _phase_authority_refusal(
    phase: CMJPhaseOccurrence,
    missing_information: tuple[str, ...],
) -> RefusalResult:
    return _metric_refusal(
        "validate RES-39 phase execution authority for RES-65",
        (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
        missing_information,
        (phase.source_observation_id, phase.source_velocity_observation_id),
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
    )


def _validate_res39_phase_authority(phase: CMJPhaseOccurrence) -> RefusalResult | None:
    """Validate RES-39 fields against the runs that actually produced them.

    RES-39 phase and boundary dataclasses intentionally remain historical
    wire objects.  RES-65 validates the authority it consumes instead of
    changing those objects or their serialized meaning.
    """

    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "validate RES-39 phase execution authority for RES-65",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJPhaseOccurrence",),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )

    for boundary in (phase.start_boundary, phase.end_boundary):
        matching_runs = tuple(
            run
            for run in boundary.provenance.processing_runs
            if run.output_entity_id == boundary.boundary_id
        )
        if len(matching_runs) != 1:
            return _phase_authority_refusal(
                phase,
                (f"exactly one RES-39 processing run producing {boundary.boundary_id.qualified}",),
            )
        run = matching_runs[0]
        if run.method != boundary.method:
            return _phase_authority_refusal(
                phase,
                (
                    f"RES-39 boundary run method equal to {boundary.boundary_id.qualified}"
                    " boundary.method",
                ),
            )
        if boundary.source_artifact_id not in run.source_artifact_ids:
            return _phase_authority_refusal(
                phase,
                (f"RES-39 boundary run source artifact for {boundary.boundary_id.qualified}",),
            )
        expected_parameters = {
            "phase_system": boundary.phase_system.stable_id,
            "boundary_kind": boundary.kind.value,
            "boundary_method": boundary.method.stable_id,
            "search_start_index": boundary.search_start_index,
            "search_end_index": boundary.search_end_index,
            "selected_sample_index": boundary.sample_index,
            "tie_policy": boundary.tie_policy,
            "velocity_threshold_policy": boundary.velocity_threshold_policy,
            "interpolation_policy": boundary.interpolation_policy,
            "source_velocity_observation_id": boundary.source_velocity_observation_id.qualified,
            "source_velocity_series_id": boundary.source_velocity_series_id.qualified,
            "source_timebase": canonical_json(boundary.source_timebase),
            "source_system_contract": canonical_json(phase.source_system_contract),
            "source_event_id": (
                boundary.source_event_id.qualified if boundary.source_event_id is not None else None
            ),
            "source_event_definition": (
                boundary.source_event_definition.stable_id
                if boundary.source_event_definition is not None
                else None
            ),
            "source_event_method": (
                boundary.source_event_method.stable_id
                if boundary.source_event_method is not None
                else None
            ),
            "source_event_parameters": boundary.source_event_parameters,
            "source_event_effective_threshold_n": boundary.source_event_effective_threshold_n,
        }
        for key, expected in expected_parameters.items():
            if _processing_run_parameter(run, key) != expected:
                return _phase_authority_refusal(
                    phase,
                    (
                        f"RES-39 boundary {boundary.boundary_id.qualified} field "
                        f"{key} equal to its producing run",
                    ),
                )

        if (
            boundary.phase_system != phase.phase_system
            or boundary.source_observation_id != phase.source_observation_id
            or boundary.source_signal_id != phase.source_signal_id
            or boundary.source_artifact_id != phase.source_artifact_id
            or boundary.source_acquisition_id != phase.source_acquisition_id
            or boundary.source_measurement_identity_id
            != phase.source_measurement_identity.identity_id
            or boundary.source_velocity_observation_id != phase.source_velocity_observation_id
            or boundary.source_velocity_series_id != phase.source_velocity_series_id
        ):
            return _phase_authority_refusal(
                phase,
                ("phase occurrence and both RES-39 boundary source identities",),
            )

    matching_phase_runs = tuple(
        run
        for run in phase.provenance.processing_runs
        if run.output_entity_id == phase.occurrence_id
    )
    if len(matching_phase_runs) != 1:
        return _phase_authority_refusal(
            phase,
            ("exactly one RES-39 processing run producing the phase occurrence",),
        )
    phase_run = matching_phase_runs[0]
    if phase_run.method != phase.phase_system:
        return _phase_authority_refusal(
            phase,
            ("RES-39 phase-occurrence run method equal to phase.phase_system",),
        )

    expected_phase_parameters = {
        "phase_system": phase.phase_system.stable_id,
        "phase_definition": phase.phase_definition.stable_id,
        "source_observation_id": phase.source_observation_id.qualified,
        "source_signal_id": phase.source_signal_id.qualified,
        "source_velocity_observation_id": phase.source_velocity_observation_id.qualified,
        "source_velocity_series_id": phase.source_velocity_series_id.qualified,
        "start_boundary_id": phase.start_boundary.boundary_id.qualified,
        "end_boundary_id": phase.end_boundary.boundary_id.qualified,
        "boundary_convention": phase.boundary_convention.stable_id,
        "sample_support": canonical_json(phase.sample_support),
        "interpolation_policy": phase.interpolation_policy,
        "velocity_threshold_policy": phase.velocity_threshold_policy,
        "source_velocity_initial_condition": canonical_json(
            phase.source_velocity_initial_condition
        ),
        "source_velocity_integration_interval": canonical_json(
            phase.source_velocity_integration_interval
        ),
        "source_velocity_source_signal_ids": canonical_json(
            phase.source_velocity_source_signal_ids
        ),
        "source_velocity_source_observation_ids": canonical_json(
            phase.source_velocity_source_observation_ids
        ),
        "source_velocity_source_measurement_identity_ids": canonical_json(
            phase.source_velocity_source_measurement_identity_ids
        ),
        "source_velocity_version": canonical_json(phase.source_velocity_version),
        "source_system_contract": canonical_json(phase.source_system_contract),
    }
    for key, expected in expected_phase_parameters.items():
        if _processing_run_parameter(phase_run, key) != expected:
            return _phase_authority_refusal(
                phase,
                (f"RES-39 phase-occurrence field {key} equal to its producing run",),
            )

    expected_source_event_ids = tuple(
        boundary.source_event_id
        for boundary in (phase.start_boundary, phase.end_boundary)
        if boundary.source_event_id is not None
    )
    if phase.source_event_ids != expected_source_event_ids:
        return _phase_authority_refusal(
            phase,
            ("phase source_event_ids equal to its boundary event authority",),
        )
    if phase.source_artifact_id not in tuple(
        artifact.artifact_id for artifact in phase.provenance.source_artifacts
    ) or phase.source_acquisition_id not in tuple(
        acquisition.acquisition_id for acquisition in phase.provenance.acquisitions
    ):
        return _phase_authority_refusal(
            phase,
            ("phase source artifact and acquisition preserved in provenance",),
        )
    if (
        phase.start_time_s != phase.start_boundary.boundary_time_s
        or phase.end_time_s != phase.end_boundary.boundary_time_s
        or phase.start_boundary.sample_index != phase.sample_support.start_index
        or phase.end_boundary.sample_index != phase.sample_support.end_index
    ):
        return _phase_authority_refusal(
            phase,
            ("phase times and sample support equal to current boundary authority",),
        )
    if (
        phase.source_velocity_operation
        != phase.source_velocity_measurement_identity.processing.registered_operation
        or phase.source_velocity_integration_method
        != phase.source_velocity_integration_interval.integration_method
    ):
        return _phase_authority_refusal(
            phase,
            ("phase velocity operation and integration method preserve source authority",),
        )
    return None


def _validate_phase_source(
    total: TotalSupportedForceResult,
    phase: CMJPhaseOccurrence,
) -> RefusalResult | None:
    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "validate RES-65 phase source",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJPhaseOccurrence",),
            (total.observation.observation_id,),
        )
    authority_refusal = _validate_res39_phase_authority(phase)
    if authority_refusal is not None:
        return authority_refusal
    identity = total.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return _metric_refusal(
            "validate RES-65 phase source",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJ total-force measurement identity",),
        )
    if (
        phase.source_context != total.observation.context
        or phase.source_observation_id != total.observation.observation_id
        or phase.source_signal_id != total.signal.signal_id
        or phase.source_artifact_id != total.source_artifact.artifact_id
        or phase.source_acquisition_id != total.acquisition.acquisition_id
        or phase.source_measurement_identity != identity
        or phase.start_boundary.source_timebase != total.signal.timebase
        or phase.sample_support.end_index >= len(total.signal.samples)
    ):
        return _metric_refusal(
            "validate RES-65 phase source",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            (
                "phase occurrence from the exact total supported-force source, "
                "including its complete observation context",
            ),
            (total.observation.observation_id, phase.source_velocity_observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _support_for_metric(
    metric: CMJForceMetric,
    total: TotalSupportedForceResult,
    *,
    phase: CMJPhaseOccurrence | None,
    movement_onset: CMJEventOccurrence | None,
    takeoff: CMJEventOccurrence | None,
) -> CMJMetricSupport | RefusalResult:
    spec = _force_spec(metric)
    identity = total.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return _metric_refusal(
            "construct RES-65 force metric support",
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ total-force measurement identity",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_observation_id = total.observation.observation_id
    source_signal_id = total.signal.signal_id
    source_artifact_id = total.source_artifact.artifact_id
    source_acquisition_id = total.acquisition.acquisition_id
    source_measurement_identity_id = identity.identity_id
    source_sample_count = len(total.signal.samples)
    source_timebase = _required_signal_timebase(total.signal)
    if spec.support_kind is CMJMetricSupportKind.WHOLE_MOVEMENT:
        if (
            phase is not None
            or not isinstance(movement_onset, CMJEventOccurrence)
            or not isinstance(takeoff, CMJEventOccurrence)
        ):
            return _metric_refusal(
                "construct RES-65 whole-movement force metric support",
                (RefusalReasonCode.EVENT_BOUNDARY_MISMATCH,),
                ("exact movement-onset and takeoff events, without a phase occurrence",),
                (total.observation.observation_id,),
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
        try:
            support = CMJMetricSupport(
                kind=spec.support_kind,
                source_observation_id=source_observation_id,
                source_signal_id=source_signal_id,
                source_artifact_id=source_artifact_id,
                source_acquisition_id=source_acquisition_id,
                source_measurement_identity_id=source_measurement_identity_id,
                source_sample_count=source_sample_count,
                source_timebase=source_timebase,
                start_index=movement_onset.sample_index,
                end_index=takeoff.sample_index,
                start_time_s=movement_onset.event_time_s,
                end_time_s=takeoff.event_time_s,
                movement_onset=movement_onset,
                takeoff=takeoff,
            )
        except (TypeError, ValueError) as exc:
            return _metric_refusal(
                "construct RES-65 whole-movement force metric support",
                (RefusalReasonCode.EVENT_BOUNDARY_MISMATCH,),
                (f"exact RES-36 movement support: {exc}",),
                (total.observation.observation_id,),
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
        return support
    if phase is None or movement_onset is not None or takeoff is not None:
        return _metric_refusal(
            "construct RES-65 phase force metric support",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("exact RES-39 braking or propulsion phase occurrence",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    phase_refusal = _validate_phase_source(total, phase)
    if phase_refusal is not None:
        return phase_refusal
    expected_kind = (
        CMJMetricSupportKind.BRAKING
        if phase.label is CMJPhaseLabel.BRAKING
        else CMJMetricSupportKind.PROPULSION
        if phase.label is CMJPhaseLabel.PROPULSION
        else None
    )
    if expected_kind is not spec.support_kind:
        return _metric_refusal(
            "construct RES-65 phase force metric support",
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            (f"phase occurrence labelled {spec.support_kind.value}",),
            (phase.source_velocity_observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        return CMJMetricSupport(
            kind=spec.support_kind,
            source_observation_id=source_observation_id,
            source_signal_id=source_signal_id,
            source_artifact_id=source_artifact_id,
            source_acquisition_id=source_acquisition_id,
            source_measurement_identity_id=source_measurement_identity_id,
            source_sample_count=source_sample_count,
            source_timebase=source_timebase,
            start_index=phase.sample_support.start_index,
            end_index=phase.sample_support.end_index,
            start_time_s=phase.start_time_s,
            end_time_s=phase.end_time_s,
            phase_occurrence=phase,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            "construct RES-65 phase force metric support",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            (f"registered phase sample support: {exc}",),
            (phase.source_velocity_observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def _force_value(
    total: TotalSupportedForceResult,
    support: CMJMetricSupport,
    statistic: str,
) -> float:
    values = total.signal.samples[support.start_index : support.end_index + 1]
    if statistic == "SAMPLE_MAXIMUM":
        return float(max(values))
    if statistic != "TIME_WEIGHTED_TRAPEZOIDAL_MEAN":
        raise ValueError("force statistic is not registered")
    return _time_weighted_mean(
        values,
        _required_signal_timebase(total.signal),
        support.start_index,
        support.end_index,
    )


def _time_weighted_mean(
    values: tuple[float, ...], timebase: SignalTimebase, start_index: int, end_index: int
) -> float:
    if len(values) != end_index - start_index + 1 or end_index <= start_index:
        raise ValueError("time mean requires inclusive support with at least one interval")
    area = math.fsum(
        0.5
        * (values[offset - 1] + values[offset])
        * (_time_at(timebase, start_index + offset) - _time_at(timebase, start_index + offset - 1))
        for offset in range(1, len(values))
    )
    duration = _time_at(timebase, end_index) - _time_at(timebase, start_index)
    if duration <= 0 or not math.isfinite(duration):
        raise ValueError("time mean requires a positive finite support duration")
    return area / duration


def _build_scalar_observation(
    *,
    source_identity: CMJMeasurementIdentity,
    source_context: ObservationContext,
    source_provenance: Provenance,
    source_observations: tuple[ScientificMeasurementObservation, ...],
    source_entities: tuple[InstanceIdentifier, ...],
    value: float,
    unit: UnitReference,
    measurand: RegistryReference,
    metric: RegistryReference,
    operation: RegistryReference,
    method_parameters: tuple[MetadataEntry, ...],
    event_definitions: tuple[RegistryReference, ...] = (),
    phase_definitions: tuple[RegistryReference, ...] = (),
    filtering: tuple[RegistryReference, ...] = (),
    integration_method: RegistryReference | None = None,
    value_origin: ValueOrigin = ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
    output_observation_id: InstanceIdentifier | None = None,
    extra_output_artifacts: tuple[SourceArtifact, ...] = (),
) -> ScientificMeasurementObservation:
    _finite(value, "metric result")
    if not source_provenance.source_artifacts:
        raise ValueError("RES-65 result requires source artifact provenance")
    if source_identity.acquisition.sign_convention is None:
        raise ValueError("RES-65 result requires a source sign convention")
    digest = canonical_hash(
        {
            "metric": metric,
            "operation": operation,
            "value": value,
            "parameters": method_parameters,
            "source_entities": source_entities,
            "output_observation_id": output_observation_id,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"cmj-res65:{digest}"
    )
    if observation_id.instance_type != "observation":
        raise ValueError("output_observation_id must identify an observation")
    source_observation_ids = tuple(item.observation_id for item in source_observations)
    if observation_id in source_observation_ids:
        raise ValueError("RES-65 output observation must differ from its source observations")
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"cmj-res65:{digest}"),
        content_digest=canonical_hash(
            {"value": value, "unit": unit, "metric": metric, "parameters": method_parameters}
        ),
        media_type="application/vnd.dynamislm.cmj.res65-scalar-metric",
        immutable=True,
    )
    output_processing = ProcessingIdentity(
        event_definitions=event_definitions,
        phase_definitions=phase_definitions,
        registered_operation=operation,
        method_parameters=method_parameters,
        filtering=filtering,
        integration_method=integration_method,
        unit=unit,
        sign_convention=source_identity.acquisition.sign_convention,
    )
    identity = CMJMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", f"cmj-res65-{digest}", CMJ_REGISTRY_VERSION
        ),
        semantic=CMJSemanticIdentity(
            construct=CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
            test_family=CMJ_TEST_FAMILY,
            protocol=source_identity.semantic.protocol,
            measurand=measurand,
            metric_definition=metric,
            protocol_identity=source_identity.semantic.protocol_identity,
        ),
        acquisition=source_identity.acquisition,
        processing=output_processing,
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=CMJ_REGISTRY_VERSION,
            software_version=RES65_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-res65:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (artifact.artifact_id for artifact in source_provenance.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=operation,
        parameters=method_parameters,
        software_version=RES65_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        source_provenance,
        processing_run=processing_run,
        output_entity_id=observation_id,
        source_observation_ids=source_observation_ids,
        source_acquisition_ids=tuple(
            acquisition.acquisition_id for acquisition in source_provenance.acquisitions
        ),
        output_artifacts=(output_artifact, *extra_output_artifacts),
        produced_artifact_ids=(
            output_artifact.artifact_id,
            *(item.artifact_id for item in extra_output_artifacts),
        ),
        supported_by=(RES65_DECISION_CMJ_METRIC_COMPLETION,),
        evidence_references=(
            EvidenceReference(RES65_DECISION_CMJ_METRIC_COMPLETION, "registered RES-65 metric"),
        ),
        recorded_at=source_context.observed_at,
    )
    edges = list(provenance.lineage_edges)
    for entity_id in source_entities:
        edge = LineageEdge(
            entity_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges and entity_id != processing_run.processing_run_id:
            edges.append(edge)
    provenance = replace(provenance, lineage_edges=tuple(edges))
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=source_context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"cmj-res65:{digest}"),
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(value_origin, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=_UNCERTAINTY_NOTE,
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


def calculate_cmj_force_metric(
    force: CMJForceInput | TotalSupportedForceResult,
    metric: CMJForceMetric,
    *,
    counterpart: CMJForceInput | None = None,
    phase: CMJPhaseOccurrence | None = None,
    movement_onset: CMJEventOccurrence | None = None,
    takeoff: CMJEventOccurrence | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    """Calculate one registered total-supported-force peak or time mean."""

    claim = "calculate registered RES-65 CMJ force metric"
    if not isinstance(metric, CMJForceMetric):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered CMJForceMetric",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        spec = _force_spec(metric)
    except ValueError:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered RES-65 force operation",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    total = _validated_total_force(force, counterpart, claim)
    if isinstance(total, RefusalResult):
        return total
    support = _support_for_metric(
        metric, total, phase=phase, movement_onset=movement_onset, takeoff=takeoff
    )
    if isinstance(support, RefusalResult):
        return support
    try:
        value = _force_value(total, support, spec.statistic)
    except (TypeError, ValueError, OverflowError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            (f"deterministic force arithmetic: {exc}",),
            (total.observation.observation_id,),
        )
    identity = total.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ source measurement identity",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    phase_definitions = (
        (support.phase_occurrence.phase_definition,) if support.phase_occurrence is not None else ()
    )
    events = tuple(
        event for event in (support.movement_onset, support.takeoff) if event is not None
    )
    parameters = (
        MetadataEntry("metric", metric.value),
        MetadataEntry("metric_definition", spec.metric_reference.stable_id),
        MetadataEntry("operation_id", spec.operation.stable_id),
        MetadataEntry("operation_version", spec.operation.identifier.version),
        MetadataEntry("statistic", spec.statistic),
        MetadataEntry("support_kind", support.kind.value),
        MetadataEntry("sample_convention", support.sample_convention.stable_id),
        MetadataEntry("start_index", support.start_index),
        MetadataEntry("end_index", support.end_index),
        MetadataEntry("start_time_s", support.start_time_s),
        MetadataEntry("end_time_s", support.end_time_s),
        MetadataEntry("source_force_observation_id", total.observation.observation_id.qualified),
        MetadataEntry("source_force_signal_id", total.signal.signal_id.qualified),
        MetadataEntry("source_force_artifact_id", total.source_artifact.artifact_id.qualified),
        MetadataEntry("source_force_acquisition_id", total.acquisition.acquisition_id.qualified),
        MetadataEntry("source_force_measurement_identity_id", identity.identity_id.stable_id),
        MetadataEntry("source_force_timebase", canonical_json(total.signal.timebase)),
        MetadataEntry("force_quantity", "TOTAL_SUPPORTED_VERTICAL_FORCE"),
        MetadataEntry("interpolation", "none"),
        MetadataEntry("filtering", canonical_json(identity.processing.filtering)),
        MetadataEntry(
            "equation",
            "sample_maximum(F_total_supported_vertical)"
            if spec.statistic == "SAMPLE_MAXIMUM"
            else "integral(F_total_supported_vertical dt) / duration",
        ),
    )
    base = total.observation.provenance
    for event in events:
        base = _merge_provenance(base, event.provenance)
    try:
        observation = _build_scalar_observation(
            source_identity=identity,
            source_context=total.observation.context,
            source_provenance=base,
            source_observations=(total.observation,),
            source_entities=(
                total.observation.observation_id,
                total.signal.signal_id,
                *(event.occurrence_id for event in events),
                *((phase.occurrence_id,) if phase is not None else ()),
            ),
            value=value,
            unit=NEWTON,
            measurand=CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND,
            metric=spec.metric_reference,
            operation=spec.operation,
            method_parameters=parameters,
            event_definitions=tuple(event.definition.reference for event in events),
            phase_definitions=phase_definitions,
            filtering=identity.processing.filtering,
            integration_method=(
                CMJ_TRAPEZOIDAL_INTEGRATION_METHOD
                if spec.statistic == "TIME_WEIGHTED_TRAPEZOIDAL_MEAN"
                else None
            ),
            output_observation_id=output_observation_id,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"registered force result construction: {exc}",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return CMJForceMetricResult(observation, metric, total, support)


def calculate_cmj_whole_movement_peak_total_supported_vertical_force(
    force: CMJForceInput | TotalSupportedForceResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    return calculate_cmj_force_metric(
        force,
        CMJForceMetric.WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE,
        counterpart=counterpart,
        movement_onset=movement_onset,
        takeoff=takeoff,
        output_observation_id=output_observation_id,
    )


def calculate_cmj_whole_movement_time_mean_total_supported_vertical_force(
    force: CMJForceInput | TotalSupportedForceResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    return calculate_cmj_force_metric(
        force,
        CMJForceMetric.WHOLE_MOVEMENT_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE,
        counterpart=counterpart,
        movement_onset=movement_onset,
        takeoff=takeoff,
        output_observation_id=output_observation_id,
    )


def calculate_cmj_phase_force_metric(
    force: CMJForceInput | TotalSupportedForceResult,
    phase: CMJPhaseOccurrence,
    metric: CMJForceMetric,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    return calculate_cmj_force_metric(
        force,
        metric,
        counterpart=counterpart,
        phase=phase,
        output_observation_id=output_observation_id,
    )


def calculate_cmj_phase_peak_total_supported_vertical_force(
    phase: CMJPhaseOccurrence,
    force: CMJForceInput | TotalSupportedForceResult,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    """Calculate sampled phase peak force using the phase-first call shape."""

    metric = (
        CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE
        if phase.label is CMJPhaseLabel.BRAKING
        else CMJForceMetric.PROPULSION_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE
    )
    return calculate_cmj_force_metric(
        force,
        metric,
        counterpart=counterpart,
        phase=phase,
        output_observation_id=output_observation_id,
    )


def calculate_cmj_phase_time_mean_total_supported_vertical_force(
    phase: CMJPhaseOccurrence,
    force: CMJForceInput | TotalSupportedForceResult,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceMetricResult | RefusalResult:
    """Calculate a time-weighted phase mean force using the phase-first call shape."""

    metric = (
        CMJForceMetric.BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE
        if phase.label is CMJPhaseLabel.BRAKING
        else CMJForceMetric.PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE
    )
    return calculate_cmj_force_metric(
        force,
        metric,
        counterpart=counterpart,
        phase=phase,
        output_observation_id=output_observation_id,
    )


def _validate_power_binding(
    total: TotalSupportedForceResult,
    velocity: SupportedSystemComVelocityResult,
    phase: CMJPhaseOccurrence,
) -> RefusalResult | None:
    if not isinstance(velocity, SupportedSystemComVelocityResult):
        return _metric_refusal(
            "validate RES-65 power source",
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("SupportedSystemComVelocityResult",),
            (total.observation.observation_id,),
        )
    observation_ids = (total.observation.observation_id, velocity.observation.observation_id)
    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "validate RES-65 power source",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJPhaseOccurrence",),
            observation_ids,
        )
    phase_refusal = _validate_phase_source(total, phase)
    if phase_refusal is not None:
        return phase_refusal
    identity = total.observation.identity
    velocity_identity = velocity.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity) or not isinstance(
        velocity_identity, CMJMeasurementIdentity
    ):
        return _metric_refusal(
            "validate RES-65 power source",
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ force and velocity identities",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        velocity.system_contract != phase.source_system_contract
        or not velocity.system_contract.is_authorized
        or identity.acquisition != velocity_identity.acquisition
        or identity.acquisition.processing_state != velocity_identity.acquisition.processing_state
        or total.observation.context != velocity.observation.context
        or phase.source_context != total.observation.context
        or identity.semantic.protocol_identity != velocity_identity.semantic.protocol_identity
        or identity.processing.filtering != velocity_identity.processing.filtering
        or total.signal.timebase != velocity.series.timebase
        or total.signal.signal_id not in velocity.series.source_signal_ids
        or total.observation.observation_id not in velocity.series.source_observation_ids
        or total.source_artifact.artifact_id not in velocity.series.source_artifact_ids
        or identity.identity_id not in velocity.series.source_measurement_identity_ids
        or velocity.series.source_sample_count != len(total.signal.samples)
        or phase.source_velocity_observation_id != velocity.observation.observation_id
        or phase.source_velocity_series_id != velocity.series.series_id
    ):
        return _metric_refusal(
            "validate RES-65 power source",
            (
                RefusalReasonCode.PHASE_SOURCE_MISMATCH,
                RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,
            ),
            (
                "total supported force and supported-system COM velocity from the same "
                "physical system, trial, source support, and timebase",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        phase.sample_support.start_index < velocity.series.sample_start_index
        or phase.sample_support.end_index
        >= velocity.series.sample_start_index + len(velocity.samples)
    ):
        return _metric_refusal(
            "validate RES-65 power source",
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            ("velocity series support for both phase endpoints",),
            observation_ids,
        )
    return None


def _power_samples(
    total: TotalSupportedForceResult,
    velocity: SupportedSystemComVelocityResult,
    phase: CMJPhaseOccurrence,
) -> tuple[float, ...]:
    values: list[float] = []
    for index in range(phase.sample_support.start_index, phase.sample_support.end_index + 1):
        local_index = index - velocity.series.sample_start_index
        if not 0 <= local_index < len(velocity.samples):
            raise ValueError("velocity sample support does not cover power phase")
        values.append(total.signal.samples[index] * velocity.samples[local_index])
    return tuple(values)


def _power_value(
    samples: tuple[float, ...],
    phase: CMJPhaseOccurrence,
    timebase: SignalTimebase,
    statistic: str,
) -> float:
    if statistic == "SAMPLED_MINIMUM":
        value = min(samples)
        if value >= 0.0:
            raise ValueError("braking peak power requires a negative sampled value")
        return value
    if statistic == "SAMPLED_MAXIMUM":
        value = max(samples)
        if value <= 0.0:
            raise ValueError("propulsion peak power requires a positive sampled value")
        return value
    if statistic == "TIME_WEIGHTED_TRAPEZOIDAL_MEAN":
        return _time_weighted_mean(
            samples,
            timebase,
            phase.sample_support.start_index,
            phase.sample_support.end_index,
        )
    raise ValueError("power statistic is not registered")


def calculate_cmj_power_metric(
    force: CMJForceInput | TotalSupportedForceResult,
    velocity: SupportedSystemComVelocityResult,
    phase: CMJPhaseOccurrence,
    metric: CMJPowerMetric,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJPowerResult | RefusalResult:
    """Calculate one signed RES-65 total-force x COM-velocity phase power metric."""

    claim = "calculate registered RES-65 CMJ power metric"
    if not isinstance(metric, CMJPowerMetric):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered CMJPowerMetric",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        spec = _power_spec(metric)
    except ValueError:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered RES-65 power operation",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    total = _validated_total_force(force, counterpart, claim)
    if isinstance(total, RefusalResult):
        return total
    binding = _validate_power_binding(total, velocity, phase)
    if binding is not None:
        return binding
    if phase.label is not spec.phase_label:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            (f"phase occurrence labelled {spec.phase_label.value}",),
            (phase.source_velocity_observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        samples = _power_samples(total, velocity, phase)
        value = _power_value(
            samples,
            phase,
            _required_signal_timebase(total.signal),
            spec.statistic,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        reason = (
            RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH
            if "support" in str(exc)
            else RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE
        )
        return _metric_refusal(
            claim,
            (reason,),
            (f"signed power arithmetic: {exc}",),
            (total.observation.observation_id, velocity.observation.observation_id),
        )
    force_identity = total.observation.identity
    velocity_identity = velocity.observation.identity
    if not isinstance(force_identity, CMJMeasurementIdentity) or not isinstance(
        velocity_identity, CMJMeasurementIdentity
    ):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ force and velocity identities",),
            (total.observation.observation_id, velocity.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    series_digest = canonical_hash(
        {
            "operation": CMJ_POWER_SERIES_OPERATION,
            "source_force": total.observation.observation_id,
            "source_signal": total.signal.signal_id,
            "source_velocity": velocity.observation.observation_id,
            "source_velocity_series": velocity.series.series_id,
            "phase": phase.occurrence_id,
            "samples": samples,
            "timebase": total.signal.timebase,
        }
    ).removeprefix("sha256:")[:24]
    series_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"cmj-res65-power-series:{series_digest}"),
        content_digest=canonical_hash({"samples": samples, "timebase": total.signal.timebase}),
        media_type="application/vnd.dynamislm.cmj.res65-power-series",
        immutable=True,
    )
    series = CMJPowerSeries(
        series_id=InstanceIdentifier("signal", f"cmj-res65-power-series:{series_digest}"),
        artifact_id=series_artifact.artifact_id,
        source_force_observation_id=total.observation.observation_id,
        source_force_signal_id=total.signal.signal_id,
        source_force_artifact_id=total.source_artifact.artifact_id,
        source_force_acquisition_id=total.acquisition.acquisition_id,
        source_force_measurement_identity_id=force_identity.identity_id,
        source_velocity_observation_id=velocity.observation.observation_id,
        source_velocity_series_id=velocity.series.series_id,
        source_velocity_measurement_identity_id=velocity_identity.identity_id,
        source_sample_count=len(total.signal.samples),
        sample_start_index=phase.sample_support.start_index,
        samples=samples,
        timebase=_required_signal_timebase(total.signal),
        unit=WATT,
        operation=CMJ_POWER_SERIES_OPERATION,
        system_contract=velocity.system_contract,
        phase_occurrence=phase,
        sign_convention=_required_signal_sign(total.signal),
    )
    parameters = (
        MetadataEntry("metric", metric.value),
        MetadataEntry("metric_definition", spec.metric_reference.stable_id),
        MetadataEntry("operation_id", spec.operation.stable_id),
        MetadataEntry("operation_version", spec.operation.identifier.version),
        MetadataEntry("statistic", spec.statistic),
        MetadataEntry("power_force_identity", "TOTAL_SUPPORTED_VERTICAL_FORCE"),
        MetadataEntry("power_velocity_identity", "SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY"),
        MetadataEntry("power_force_operation", CMJ_POWER_SERIES_OPERATION.stable_id),
        MetadataEntry("power_velocity_operation", velocity.series.operation.stable_id),
        MetadataEntry(
            "power_velocity_integration_method",
            velocity.series.integration_method.stable_id
            if velocity.series.integration_method
            else "unresolved",
        ),
        MetadataEntry("power_series_id", series.series_id.qualified),
        MetadataEntry("power_series_schema", CMJ_POWER_SERIES_SCHEMA.stable_id),
        MetadataEntry("phase_system", phase.phase_system.stable_id),
        MetadataEntry("phase_definition", phase.phase_definition.stable_id),
        MetadataEntry("phase_occurrence_id", phase.occurrence_id.qualified),
        MetadataEntry("source_force_observation_id", total.observation.observation_id.qualified),
        MetadataEntry("source_force_signal_id", total.signal.signal_id.qualified),
        MetadataEntry(
            "source_velocity_observation_id", velocity.observation.observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", velocity.series.series_id.qualified),
        MetadataEntry("source_timebase", canonical_json(total.signal.timebase)),
        MetadataEntry("source_system_contract", canonical_json(velocity.system_contract)),
        MetadataEntry("signed_power", "no_absolute_value"),
        MetadataEntry("mean_power_method", spec.statistic),
        MetadataEntry("interpolation", "none"),
        MetadataEntry("filtering", canonical_json(velocity_identity.processing.filtering)),
        MetadataEntry(
            "equation", "P_total = F_total_supported_vertical * v_supported_system_COM_vertical"
        ),
    )
    base = _merge_provenance(
        _merge_provenance(total.observation.provenance, velocity.observation.provenance),
        phase.provenance,
    )
    try:
        observation = _build_scalar_observation(
            source_identity=velocity_identity,
            source_context=velocity.observation.context,
            source_provenance=base,
            source_observations=(total.observation, velocity.observation),
            source_entities=(
                total.observation.observation_id,
                total.signal.signal_id,
                velocity.observation.observation_id,
                velocity.series.series_id,
                phase.occurrence_id,
            ),
            value=value,
            unit=WATT,
            measurand=CMJ_SUPPORTED_SYSTEM_EXTERNAL_MECHANICAL_POWER_MEASURAND,
            metric=spec.metric_reference,
            operation=spec.operation,
            method_parameters=parameters,
            phase_definitions=(phase.phase_definition,),
            filtering=velocity_identity.processing.filtering,
            integration_method=(
                CMJ_TRAPEZOIDAL_INTEGRATION_METHOD if "TIME_WEIGHTED" in spec.statistic else None
            ),
            extra_output_artifacts=(series_artifact,),
            output_observation_id=output_observation_id,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"registered power result construction: {exc}",),
            (total.observation.observation_id, velocity.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return CMJPowerResult(observation, metric, total, velocity, phase, series)


def calculate_cmj_phase_power_metric(
    phase: CMJPhaseOccurrence,
    force: CMJForceInput | TotalSupportedForceResult,
    velocity: SupportedSystemComVelocityResult,
    metric: CMJPowerMetric,
    *,
    counterpart: CMJForceInput | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJPowerResult | RefusalResult:
    """Calculate power using the phase-first RES-39 helper call shape."""

    return calculate_cmj_power_metric(
        force,
        velocity,
        phase,
        metric,
        counterpart=counterpart,
        output_observation_id=output_observation_id,
    )


def _validate_takeoff_velocity_binding(
    velocity: SupportedSystemComVelocityResult,
    takeoff: CMJEventOccurrence,
) -> RefusalResult | None:
    if not isinstance(velocity, SupportedSystemComVelocityResult):
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (RefusalReasonCode.TAKEOFF_VELOCITY_REQUIRED,),
            ("SupportedSystemComVelocityResult",),
            (),
        )
    if not isinstance(takeoff, CMJEventOccurrence):
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("CMJEventOccurrence takeoff input",),
            (velocity.observation.observation_id,),
        )
    observation_ids = (velocity.observation.observation_id, takeoff.source_observation_id)
    if (
        takeoff.detector_method != CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD
        or takeoff.definition.label is not CMJEventLabel.TAKEOFF_CONTACT_LOSS
        or takeoff.status is not CMJEventOccurrenceStatus.DETECTED
    ):
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            ("registered RES-36 takeoff/contact-loss event",),
            observation_ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    condition = velocity.initial_velocity_condition
    if not isinstance(condition, QualifiedZeroVelocityReference) or not condition.is_authorized:
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,),
            ("authorized RES-46 qualified zero-velocity reference",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        takeoff.source_signal_id not in velocity.series.source_signal_ids
        or takeoff.source_artifact_id not in velocity.series.source_artifact_ids
        or takeoff.source_observation_id not in velocity.series.source_observation_ids
        or takeoff.source_measurement_identity.identity_id
        not in velocity.series.source_measurement_identity_ids
        or takeoff.source_timebase != velocity.series.timebase
        or takeoff.source_sample_count != velocity.series.source_sample_count
        or takeoff.sample_index not in velocity.series.source_sample_indices
        or not any(
            acquisition.acquisition_id == takeoff.source_acquisition_id
            for acquisition in velocity.observation.provenance.acquisitions
        )
    ):
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (
                RefusalReasonCode.EVENT_SOURCE_MISMATCH,
                RefusalReasonCode.TAKEOFF_VELOCITY_SAMPLE_UNRESOLVED,
            ),
            ("takeoff event inside the exact velocity source chain",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not velocity.system_contract.is_authorized:
        return _metric_refusal(
            "project CMJ takeoff velocity",
            (RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED,),
            ("authorized supported-system mechanics contract",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _takeoff_velocity_value(
    velocity: SupportedSystemComVelocityResult, takeoff: CMJEventOccurrence
) -> float:
    local_index = takeoff.sample_index - velocity.series.sample_start_index
    if not 0 <= local_index < len(velocity.samples):
        raise ValueError("takeoff sample is outside the velocity series")
    value = velocity.samples[local_index]
    if value < 0.0:
        raise ValueError("takeoff velocity sample must be nonnegative under upward-positive sign")
    return value


def project_cmj_takeoff_velocity(
    velocity: SupportedSystemComVelocityResult,
    takeoff: CMJEventOccurrence,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJTakeoffVelocityResult | RefusalResult:
    """Expose the exact existing velocity sample at the registered takeoff event."""

    claim = "project CMJ takeoff velocity scalar"
    binding = _validate_takeoff_velocity_binding(velocity, takeoff)
    if binding is not None:
        return binding
    try:
        value = _takeoff_velocity_value(velocity, takeoff)
    except ValueError as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.TAKEOFF_VELOCITY_SAMPLE_UNRESOLVED,),
            (str(exc),),
            (velocity.observation.observation_id, takeoff.source_observation_id),
        )
    identity = velocity.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ velocity measurement identity",),
            (velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = (
        MetadataEntry("metric_definition", CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC.stable_id),
        MetadataEntry("schema", CMJ_TAKEOFF_VELOCITY_SCALAR_SCHEMA.stable_id),
        MetadataEntry("operation_id", CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION.stable_id),
        MetadataEntry(
            "operation_version", CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION.identifier.version
        ),
        MetadataEntry("sample_convention", CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION.stable_id),
        MetadataEntry(
            "source_velocity_observation_id", velocity.observation.observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", velocity.series.series_id.qualified),
        MetadataEntry("source_velocity_operation", velocity.series.operation.stable_id),
        MetadataEntry(
            "source_velocity_integration_method",
            velocity.series.integration_method.stable_id
            if velocity.series.integration_method
            else "unresolved",
        ),
        MetadataEntry(
            "source_velocity_initial_condition", canonical_json(velocity.initial_velocity_condition)
        ),
        MetadataEntry("takeoff_event_id", takeoff.occurrence_id.qualified),
        MetadataEntry("takeoff_sample_index", takeoff.sample_index),
        MetadataEntry("takeoff_event_time_s", takeoff.event_time_s),
        MetadataEntry("takeoff_event_method", takeoff.detector_method.reference.stable_id),
        MetadataEntry("projection", "exact_source_velocity_sample; no_recomputation"),
        MetadataEntry("source_timebase", canonical_json(velocity.series.timebase)),
        MetadataEntry("filtering", canonical_json(identity.processing.filtering)),
    )
    base = _merge_provenance(velocity.observation.provenance, takeoff.provenance)
    try:
        observation = _build_scalar_observation(
            source_identity=identity,
            source_context=velocity.observation.context,
            source_provenance=base,
            source_observations=(velocity.observation,),
            source_entities=(
                velocity.observation.observation_id,
                velocity.series.series_id,
                *velocity.series.source_signal_ids,
                takeoff.occurrence_id,
            ),
            value=value,
            unit=METERS_PER_SECOND,
            measurand=CMJ_TAKEOFF_VELOCITY_SCALAR_MEASURAND,
            metric=CMJ_TAKEOFF_VELOCITY_SCALAR_METRIC,
            operation=CMJ_TAKEOFF_VELOCITY_SCALAR_PROJECTION_OPERATION,
            method_parameters=parameters,
            event_definitions=(takeoff.definition.reference,),
            filtering=identity.processing.filtering,
            output_observation_id=output_observation_id,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"takeoff velocity result construction: {exc}",),
            (velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return CMJTakeoffVelocityResult(observation, velocity, takeoff)


def _validate_rsi_binding(
    jump_height: CMJJumpHeightResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    numerator: CMJRSIModNumerator,
) -> RefusalResult | None:
    if not isinstance(jump_height, CMJJumpHeightResult):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.ESTIMATOR_MISMATCH,),
            ("CMJJumpHeightResult",),
        )
    if not isinstance(movement_onset, CMJEventOccurrence) or not isinstance(
        takeoff, CMJEventOccurrence
    ):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("movement-onset and takeoff CMJEventOccurrence inputs",),
        )
    observation_ids = (
        jump_height.observation.observation_id,
        movement_onset.source_observation_id,
        takeoff.source_observation_id,
    )
    expected_family = (
        JumpHeightEstimatorFamily.FLIGHT_TIME
        if numerator is CMJRSIModNumerator.FLIGHT_TIME_JUMP_HEIGHT
        else JumpHeightEstimatorFamily.TAKEOFF_VELOCITY
    )
    if jump_height.estimator_family is not expected_family:
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.ESTIMATOR_MISMATCH,),
            (f"jump-height estimator family {expected_family.value}",),
            observation_ids,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if jump_height.takeoff_event != takeoff:
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("jump-height result bound to this exact takeoff occurrence",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        movement_onset.detector_method != CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD
        or movement_onset.definition.label is not CMJEventLabel.MOVEMENT_ONSET
        or movement_onset.status is not CMJEventOccurrenceStatus.DETECTED
        or takeoff.detector_method != CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD
        or takeoff.definition.label is not CMJEventLabel.TAKEOFF_CONTACT_LOSS
        or takeoff.status is not CMJEventOccurrenceStatus.DETECTED
    ):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            ("registered movement-onset and takeoff event methods",),
            observation_ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if (
        movement_onset.source_observation_id != takeoff.source_observation_id
        or movement_onset.source_signal_id != takeoff.source_signal_id
        or movement_onset.source_artifact_id != takeoff.source_artifact_id
        or movement_onset.source_acquisition_id != takeoff.source_acquisition_id
        or movement_onset.source_measurement_identity != takeoff.source_measurement_identity
        or movement_onset.source_timebase != takeoff.source_timebase
        or movement_onset.source_sample_count != takeoff.source_sample_count
        or movement_onset.sample_index >= takeoff.sample_index
        or movement_onset.event_time_s >= takeoff.event_time_s
    ):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH, RefusalReasonCode.EVENT_ORDER_INVALID),
            ("same-source movement onset before takeoff",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    jump_parameters = jump_height.parameters
    if (
        jump_parameters.source_observation_id != takeoff.source_observation_id
        or jump_parameters.source_signal_id != takeoff.source_signal_id
        or jump_parameters.source_artifact_id != takeoff.source_artifact_id
        or jump_parameters.source_acquisition_id != takeoff.source_acquisition_id
        or jump_parameters.source_measurement_identity_id
        != takeoff.source_measurement_identity.identity_id
        or jump_parameters.source_timebase != takeoff.source_timebase
        or not _provenance_has_source_entity(
            jump_height.observation.provenance,
            takeoff.occurrence_id,
        )
    ):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            (
                "movement-onset and takeoff events from the exact source authority "
                "used by the jump-height result",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    duration = takeoff.event_time_s - movement_onset.event_time_s
    if duration <= 0 or not math.isfinite(duration):
        return _metric_refusal(
            "calculate CMJ RSI-modified ratio",
            (RefusalReasonCode.EVENT_ORDER_INVALID,),
            ("positive exact takeoff-minus-movement-onset duration",),
            observation_ids,
        )
    return None


def calculate_cmj_rsi_mod(
    jump_height: CMJJumpHeightResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJRSIModResult | RefusalResult:
    """Calculate RSI-mod from an exact registered JH estimator and event times."""

    claim = "calculate registered RES-65 CMJ RSI-modified ratio"
    if not isinstance(jump_height, CMJJumpHeightResult):
        return _metric_refusal(
            claim, (RefusalReasonCode.ESTIMATOR_MISMATCH,), ("CMJJumpHeightResult",)
        )
    numerator = (
        CMJRSIModNumerator.FLIGHT_TIME_JUMP_HEIGHT
        if jump_height.estimator_family is JumpHeightEstimatorFamily.FLIGHT_TIME
        else CMJRSIModNumerator.TAKEOFF_VELOCITY_JUMP_HEIGHT
    )
    binding = _validate_rsi_binding(jump_height, movement_onset, takeoff, numerator)
    if binding is not None:
        return binding
    metric, operation = _rsi_spec(numerator)
    identity = jump_height.observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ jump-height measurement identity",),
            (jump_height.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    denominator = takeoff.event_time_s - movement_onset.event_time_s
    value = jump_height.value_m / denominator
    parameters = (
        MetadataEntry("metric_definition", metric.stable_id),
        MetadataEntry("schema", CMJ_RSI_MOD_SCHEMA.stable_id),
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("operation_version", operation.identifier.version),
        MetadataEntry("numerator", numerator.value),
        MetadataEntry(
            "jump_height_observation_id", jump_height.observation.observation_id.qualified
        ),
        MetadataEntry("jump_height_estimator", jump_height.method.reference.stable_id),
        MetadataEntry("jump_height_operation", jump_height.method.operation.stable_id),
        MetadataEntry("jump_height_identity", canonical_json(jump_height.observation.identity)),
        MetadataEntry("movement_onset_event_id", movement_onset.occurrence_id.qualified),
        MetadataEntry(
            "movement_onset_event_method", movement_onset.detector_method.reference.stable_id
        ),
        MetadataEntry(
            "movement_onset_event_parameters", canonical_json(movement_onset.detector_parameters)
        ),
        MetadataEntry("takeoff_event_id", takeoff.occurrence_id.qualified),
        MetadataEntry("takeoff_event_method", takeoff.detector_method.reference.stable_id),
        MetadataEntry("takeoff_event_parameters", canonical_json(takeoff.detector_parameters)),
        MetadataEntry("source_timebase", canonical_json(takeoff.source_timebase)),
        MetadataEntry(
            "denominator_semantics", "takeoff_event_time_s - movement_onset_event_time_s"
        ),
        MetadataEntry("denominator_s", denominator),
        MetadataEntry(
            "equation", "jump_height_m / (takeoff_event_time_s - movement_onset_event_time_s)"
        ),
        MetadataEntry("filtering", canonical_json(identity.processing.filtering)),
    )
    base = _merge_provenance(
        _merge_provenance(jump_height.observation.provenance, movement_onset.provenance),
        takeoff.provenance,
    )
    source_entities = (
        jump_height.observation.observation_id,
        movement_onset.occurrence_id,
        takeoff.occurrence_id,
        takeoff.source_signal_id,
        *(
            (jump_height.source_velocity.series.series_id,)
            if jump_height.source_velocity is not None
            else ()
        ),
    )
    try:
        observation = _build_scalar_observation(
            source_identity=identity,
            source_context=jump_height.observation.context,
            source_provenance=base,
            source_observations=(jump_height.observation,),
            source_entities=source_entities,
            value=value,
            unit=METERS_PER_SECOND,
            measurand=CMJ_RSI_MOD_MEASURAND,
            metric=metric,
            operation=operation,
            method_parameters=parameters,
            event_definitions=(movement_onset.definition.reference, takeoff.definition.reference),
            filtering=identity.processing.filtering,
            value_origin=ValueOrigin.MODEL_ESTIMATE,
            output_observation_id=output_observation_id,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"RSI-mod result construction: {exc}",),
            (jump_height.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return CMJRSIModResult(observation, jump_height, movement_onset, takeoff, numerator)


def _resolve_bilateral_total(
    left: CMJForceInput,
    right: CMJForceInput,
    supplied_total: TotalSupportedForceResult | None,
    claim: str,
) -> TotalSupportedForceResult | RefusalResult:
    if not isinstance(left, CMJForceInput) or not isinstance(right, CMJForceInput):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("typed left and right CMJForceInput sources",),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_refusal = _validate_asymmetry_sources(left, right, claim)
    if source_refusal is not None:
        return source_refusal
    if supplied_total is None:
        constructed = construct_total_supported_vertical_force(left, right)
        if isinstance(constructed, RefusalResult):
            return constructed
        return constructed
    if not isinstance(supplied_total, TotalSupportedForceResult):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("typed total supported-force result",),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    reconstructed = construct_total_supported_vertical_force(
        left,
        right,
        output_entity_id=supplied_total.observation.observation_id,
        output_signal_id=supplied_total.signal.signal_id,
        output_artifact_id=supplied_total.source_artifact.artifact_id,
    )
    if isinstance(reconstructed, RefusalResult):
        return reconstructed
    if reconstructed != supplied_total:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("supplied total-force result equal to the re-executed left/right sum",),
            (supplied_total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return supplied_total


def _validate_asymmetry_sources(
    left: CMJForceInput,
    right: CMJForceInput,
    claim: str,
) -> RefusalResult | None:
    if left.observation.context != right.observation.context:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("exactly equal left/right athlete, session, test-instance, trial, and context",),
            (left.observation.observation_id, right.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    left_acquisition = left.identity.acquisition
    right_acquisition = right.identity.acquisition
    material_equal = (
        left_acquisition.device == right_acquisition.device
        and left_acquisition.measuring_system == right_acquisition.measuring_system
        and left_acquisition.hardware_firmware == right_acquisition.hardware_firmware
        and left_acquisition.sampling == right_acquisition.sampling
        and left_acquisition.timebase == right_acquisition.timebase
        and left_acquisition.acquisition_software_version
        == right_acquisition.acquisition_software_version
        and left_acquisition.calibration == right_acquisition.calibration
        and left_acquisition.zeroing == right_acquisition.zeroing
        and left_acquisition.processing_state == right_acquisition.processing_state
        and left.signal.processing_state == right.signal.processing_state
    )
    if not material_equal:
        return _metric_refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.SOURCE_PROCESSING_MISMATCH,
            ),
            (
                "matching bilateral device, measuring system, sampling, calibration, "
                "zeroing, software, and processing state",
            ),
            (left.observation.observation_id, right.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _asymmetry_values(
    left: CMJForceInput,
    right: CMJForceInput,
    phase: CMJPhaseOccurrence,
    statistic: str,
) -> tuple[float, float]:
    start = phase.sample_support.start_index
    end = phase.sample_support.end_index
    left_values = left.signal.samples[start : end + 1]
    right_values = right.signal.samples[start : end + 1]
    if statistic == "SAMPLE_MAXIMUM":
        return float(max(left_values)), float(max(right_values))
    if statistic == "TIME_WEIGHTED_TRAPEZOIDAL_MEAN":
        return (
            _time_weighted_mean(left_values, _required_signal_timebase(left.signal), start, end),
            _time_weighted_mean(right_values, _required_signal_timebase(right.signal), start, end),
        )
    raise ValueError("asymmetry statistic is not registered")


def _asymmetry_value(
    left_value: float, right_value: float, equation: CMJAsymmetryEquation
) -> float:
    if equation is not CMJAsymmetryEquation.RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT:
        raise ValueError("asymmetry equation is not registered")
    if left_value == 0.0 or not math.isfinite(left_value):
        raise ValueError("left asymmetry denominator must be finite and nonzero")
    return 100.0 * (right_value - left_value) / left_value


def calculate_cmj_force_asymmetry(
    left_source: CMJForceInput,
    right_source: CMJForceInput,
    phase: CMJPhaseOccurrence,
    metric: CMJAsymmetryMetric,
    *,
    total_force: TotalSupportedForceResult | None = None,
    equation: CMJAsymmetryEquation = CMJAsymmetryEquation.RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceAsymmetryResult | RefusalResult:
    """Calculate one exact left/right force asymmetry in a RES-39 phase."""

    claim = "calculate registered RES-65 CMJ force asymmetry"
    if not isinstance(metric, CMJAsymmetryMetric):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered CMJAsymmetryMetric",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        spec = _asymmetry_spec(metric)
    except ValueError:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered RES-65 asymmetry operation",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if equation is not CMJAsymmetryEquation.RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered right-minus-left-over-left asymmetry equation",),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    resolved = _resolve_bilateral_total(left_source, right_source, total_force, claim)
    if isinstance(resolved, RefusalResult):
        return resolved
    total = resolved
    phase_refusal = _validate_phase_source(total, phase)
    if phase_refusal is not None:
        return phase_refusal
    if phase.label is not spec.phase_label:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            (f"phase occurrence labelled {spec.phase_label.value}",),
            (phase.source_velocity_observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if not isinstance(total.signal, ProcessedVerticalForceSignal):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("re-executed bilateral total-force series with left/right source lineage",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_signal_ids = total.signal.source_signal_ids
    if (
        left_source.signal.signal_id not in source_signal_ids
        or right_source.signal.signal_id not in source_signal_ids
    ):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("total-force provenance naming both exact limb source signals",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if any(
        not _provenance_has_source_entity(total.observation.provenance, observation_id)
        for observation_id in (
            left_source.observation.observation_id,
            right_source.observation.observation_id,
        )
    ):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("total-force provenance preserving both limb observations",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    try:
        left_value, right_value = _asymmetry_values(
            left_source, right_source, phase, spec.statistic
        )
        value = _asymmetry_value(left_value, right_value, equation)
    except (TypeError, ValueError, OverflowError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            (f"deterministic asymmetry arithmetic: {exc}",),
            (left_source.observation.observation_id, right_source.observation.observation_id),
        )
    total_identity = total.observation.identity
    if not isinstance(total_identity, CMJMeasurementIdentity):
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ bilateral total-force identity",),
            (total.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = (
        MetadataEntry("metric_definition", spec.metric_reference.stable_id),
        MetadataEntry("schema", CMJ_FORCE_ASYMMETRY_SCHEMA.stable_id),
        MetadataEntry("operation_id", CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION.stable_id),
        MetadataEntry(
            "operation_version", CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION.identifier.version
        ),
        MetadataEntry("metric", metric.value),
        MetadataEntry("equation", equation.value),
        MetadataEntry("numerator_order", "right_minus_left"),
        MetadataEntry("denominator", "left_value"),
        MetadataEntry("phase_system", phase.phase_system.stable_id),
        MetadataEntry("phase_definition", phase.phase_definition.stable_id),
        MetadataEntry("phase_occurrence_id", phase.occurrence_id.qualified),
        MetadataEntry("phase_sample_support", canonical_json(phase.sample_support)),
        MetadataEntry(
            "left_source_observation_id", left_source.observation.observation_id.qualified
        ),
        MetadataEntry(
            "right_source_observation_id", right_source.observation.observation_id.qualified
        ),
        MetadataEntry("left_source_signal_id", left_source.signal.signal_id.qualified),
        MetadataEntry("right_source_signal_id", right_source.signal.signal_id.qualified),
        MetadataEntry("left_source_artifact_id", left_source.source_artifact.artifact_id.qualified),
        MetadataEntry(
            "right_source_artifact_id", right_source.source_artifact.artifact_id.qualified
        ),
        MetadataEntry("total_force_observation_id", total.observation.observation_id.qualified),
        MetadataEntry("total_force_signal_id", total.signal.signal_id.qualified),
        MetadataEntry("force_statistic", spec.statistic),
        MetadataEntry("source_timebase", canonical_json(phase.start_boundary.source_timebase)),
        MetadataEntry("interpolation", "none"),
        MetadataEntry("filtering", canonical_json(left_source.identity.processing.filtering)),
    )
    base = _merge_provenance(
        _merge_provenance(total.observation.provenance, left_source.observation.provenance),
        _merge_provenance(right_source.observation.provenance, phase.provenance),
    )
    try:
        observation = _build_scalar_observation(
            source_identity=total_identity,
            source_context=total.observation.context,
            source_provenance=base,
            source_observations=(
                left_source.observation,
                right_source.observation,
                total.observation,
            ),
            source_entities=(
                left_source.observation.observation_id,
                right_source.observation.observation_id,
                left_source.signal.signal_id,
                right_source.signal.signal_id,
                total.observation.observation_id,
                total.signal.signal_id,
                phase.occurrence_id,
            ),
            value=value,
            unit=PERCENT,
            measurand=CMJ_FORCE_ASYMMETRY_MEASURAND,
            metric=spec.metric_reference,
            operation=CMJ_LEFT_RIGHT_FORCE_ASYMMETRY_OPERATION,
            method_parameters=parameters,
            phase_definitions=(phase.phase_definition,),
            filtering=left_source.identity.processing.filtering,
            output_observation_id=output_observation_id,
        )
    except (TypeError, ValueError) as exc:
        return _metric_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"asymmetry result construction: {exc}",),
            (left_source.observation.observation_id, right_source.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return CMJForceAsymmetryResult(
        observation,
        metric,
        equation,
        left_source,
        right_source,
        total,
        phase,
        left_value,
        right_value,
    )


def calculate_cmj_phase_force_asymmetry(
    phase: CMJPhaseOccurrence,
    left_source: CMJForceInput,
    right_source: CMJForceInput,
    metric: CMJAsymmetryMetric,
    *,
    total_force: TotalSupportedForceResult | None = None,
    equation: CMJAsymmetryEquation = CMJAsymmetryEquation.RIGHT_MINUS_LEFT_OVER_LEFT_PERCENT,
    output_observation_id: InstanceIdentifier | None = None,
) -> CMJForceAsymmetryResult | RefusalResult:
    """Calculate bilateral asymmetry using the phase-first helper call shape."""

    return calculate_cmj_force_asymmetry(
        left_source,
        right_source,
        phase,
        metric,
        total_force=total_force,
        equation=equation,
        output_observation_id=output_observation_id,
    )


def refuse_unregistered_cmj_rfd(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    """Refuse RFD until onset/window/differentiation authority is registered."""

    return _metric_refusal(
        "calculate CMJ rate of force development",
        (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        (
            "registered RFD onset, window, endpoint, filtering, sampling, and "
            "differentiation method",
        ),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


def _validate_scalar_output(
    observation: ScientificMeasurementObservation,
    *,
    measurand: RegistryReference,
    metric: RegistryReference,
    operation: RegistryReference,
    unit: UnitReference,
    value_origin: ValueOrigin = ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
) -> None:
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("RES-65 scalar output requires CMJMeasurementIdentity")
    if identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
        raise ValueError("RES-65 scalar must use the supported-system construct")
    if identity.semantic.test_family.stable_id != CMJ_TEST_FAMILY.stable_id:
        raise ValueError("RES-65 scalar must use the registered CMJ test family")
    if identity.semantic.measurand.stable_id != measurand.stable_id:
        raise ValueError("RES-65 scalar has the wrong measurand")
    if identity.semantic.metric_definition.stable_id != metric.stable_id:
        raise ValueError("RES-65 scalar has the wrong metric definition")
    if (
        identity.processing.registered_operation is None
        or identity.processing.registered_operation.stable_id != operation.stable_id
    ):
        raise ValueError("RES-65 scalar has the wrong operation")
    if (
        observation.result.unit is None
        or observation.result.unit.identifier.stable_id != unit.identifier.stable_id
    ):
        raise ValueError("RES-65 scalar has the wrong unit")
    _numeric_scalar(observation)
    if observation.result.classification.value_origin is not value_origin:
        raise ValueError("RES-65 scalar has the wrong value origin")
    if observation.result.classification.scientific_roles != ():
        raise ValueError("RES-65 scalar must not infer an interpretive scientific role")
    if observation.result.status is not ResultStatus.VALID:
        raise ValueError("RES-65 scalar must be VALID")
    matching_runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(matching_runs) != 1 or matching_runs[0].method.stable_id != operation.stable_id:
        raise ValueError("RES-65 scalar must preserve one matching processing run")
    if matching_runs[0].parameters != identity.processing.method_parameters:
        raise ValueError("RES-65 processing parameters must match the processing run")


def _require_output_source_identity(
    observation: ScientificMeasurementObservation,
    source_identity: object,
) -> None:
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity) or not isinstance(
        source_identity, CMJMeasurementIdentity
    ):
        raise ValueError("RES-65 output/source identities must be CMJ identities")
    if (
        identity.semantic.protocol_identity != source_identity.semantic.protocol_identity
        or identity.acquisition != source_identity.acquisition
    ):
        raise ValueError("RES-65 output identity does not preserve its source acquisition")


def _require_exact_context(
    output_context: ObservationContext,
    source_context: ObservationContext,
    label: str,
) -> None:
    if output_context != source_context:
        raise ValueError(f"{label} observation context is not the exact source context")


def _require_result_value(observation: ScientificMeasurementObservation, expected: float) -> None:
    actual = _numeric_scalar(observation)
    if actual != expected:
        raise ValueError("RES-65 scalar value does not match its bound source arithmetic")


def _require_output_entities(
    observation: ScientificMeasurementObservation,
    entity_ids: tuple[InstanceIdentifier, ...],
) -> None:
    runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(runs) != 1:
        raise ValueError("RES-65 output must preserve one output processing run")
    run_id = runs[0].processing_run_id.qualified
    for entity_id in entity_ids:
        if not any(
            edge.from_id == entity_id.qualified
            and edge.to_id == run_id
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in observation.provenance.lineage_edges
        ):
            raise ValueError("RES-65 output is missing exact source lineage")


def _provenance_has_source_entity(provenance: Provenance, entity_id: InstanceIdentifier) -> bool:
    """Check that an entity is an input to at least one preserved processing run."""

    return any(
        edge.from_id == entity_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        and any(run.processing_run_id.qualified == edge.to_id for run in provenance.processing_runs)
        for edge in provenance.lineage_edges
    )


def _metric_method_key(value: CMJCompletedMetricResult) -> object:
    return value.method_identity_key


def cmj_metric_ranking_key(value: CMJCompletedMetricResult) -> dict[str, object]:
    """Return the trial-instance-independent key consumed by RES-50."""

    return {
        "kind": "CMJ_METRIC",
        "metric": value.observation.identity.semantic.metric_definition,
        "method": value.observation.identity.processing.registered_operation,
        "identity": _metric_method_key(value),
    }


def compare_cmj_metric_results(
    left: CMJCompletedMetricResult,
    right: CMJCompletedMetricResult,
    *,
    claim: str,
    request_id: InstanceIdentifier | None = None,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Extend CMJ comparability to RES-65 outputs without flattening methods."""

    request = CMJMetricComparabilityRequest(
        request_id=request_id
        or InstanceIdentifier(
            "comparability-request",
            f"res65:{left.observation.observation_id.value}:{right.observation.observation_id.value}",
        ),
        left_observation_id=left.observation.observation_id,
        right_observation_id=right.observation.observation_id,
        claim=claim,
        requested_transformations=requested_transformations,
    )
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    left_identity = left.observation.identity
    right_identity = right.observation.identity
    if not isinstance(left_identity, CMJMeasurementIdentity) or not isinstance(
        right_identity, CMJMeasurementIdentity
    ):
        return ComparabilityResult(
            result_id=InstanceIdentifier(
                "comparability-result", f"{request.request_id.value}:insufficient-information"
            ),
            request_id=request.request_id,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reason_codes=(ComparabilityReasonCode.MISSING_METADATA,),
            conditions=(),
            transformations_required=request.requested_transformations,
            missing_information=("CMJ RES-65 metric identities",),
            rule_reference=None,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.UNRESOLVED,
        )
    if left_identity.semantic.measurand.stable_id != right_identity.semantic.measurand.stable_id:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "measurand"))
    if (
        left_identity.semantic.metric_definition.stable_id
        != right_identity.semantic.metric_definition.stable_id
    ):
        differences.append(
            (ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH, "metric_definition")
        )
    if (
        left_identity.processing.registered_operation
        != right_identity.processing.registered_operation
    ):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "registered_operation"))
    if _metric_method_key(left) != _metric_method_key(right):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "metric_method_identity"))
    if left.observation.result.unit != right.observation.result.unit:
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "unit"))
    if left_identity.processing.normalization != right_identity.processing.normalization:
        differences.append((ComparabilityReasonCode.NORMALIZATION_MISMATCH, "normalization"))
    if left.observation.result.classification != right.observation.result.classification:
        differences.append((ComparabilityReasonCode.IDENTITY_MISMATCH, "classification"))
    if left_identity.processing.filtering != right_identity.processing.filtering:
        differences.append((ComparabilityReasonCode.FILTERING_MISMATCH, "filtering"))
    try:
        from dynamislm.measurement.cmj.comparability import compare_cmj_measurement_identities

        acquisition = compare_cmj_measurement_identities(
            left_identity,
            right_identity,
            claim=claim,
            request_id=InstanceIdentifier(
                "comparability-request", f"{request.request_id.value}:acquisition"
            ),
            left_observation_id=left.observation.observation_id,
            right_observation_id=right.observation.observation_id,
        )
    except (TypeError, ValueError):
        acquisition = None
    if acquisition is not None and acquisition.state is not ComparabilityState.COMPARABLE:
        for reason in acquisition.reason_codes:
            try:
                differences.append((ComparabilityReasonCode(reason), "acquisition"))
            except ValueError:
                differences.append(
                    (ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED, "acquisition")
                )
    if request.requested_transformations and not differences:
        return _metric_comparability_result(
            request,
            ComparabilityState.REQUIRES_TRANSFORMATION,
            (ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            conditions=("the requested registered transformation must be applied first",),
        )
    reasons = tuple(dict.fromkeys(reason for reason, _ in differences))
    if not reasons:
        return _metric_comparability_result(request, ComparabilityState.COMPARABLE)
    state = (
        ComparabilityState.NOT_COMPARABLE
        if ComparabilityReasonCode.MEASURAND_MISMATCH in reasons
        else ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )
    return _metric_comparability_result(
        request,
        state,
        reasons,
        conditions=(
            "RES-65 metric, support, source-processing, acquisition, and method identities "
            "must match or have a registered bridge",
        ),
    )


def _metric_comparability_result(
    request: CMJMetricComparabilityRequest,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
    *,
    conditions: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=conditions,
        transformations_required=request.requested_transformations,
        missing_information=(),
        rule_reference=CMJ_RES65_METRIC_COMPARABILITY_RULE,
        evidence_references=(RES65_DECISION_CMJ_METRIC_COMPLETION,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def refusal_for_cmj_metric_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    if result.state is ComparabilityState.COMPARABLE:
        return None
    mapping = {
        ComparabilityReasonCode.MEASURAND_MISMATCH: RefusalReasonCode.MEASURAND_MISMATCH,
        ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH: (
            RefusalReasonCode.METRIC_DEFINITION_MISMATCH
        ),
        ComparabilityReasonCode.IDENTITY_MISMATCH: RefusalReasonCode.METRIC_DEFINITION_MISMATCH,
        ComparabilityReasonCode.METHOD_MISMATCH: RefusalReasonCode.NO_REGISTERED_OPERATION,
        ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
        ),
        ComparabilityReasonCode.NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
        ),
        ComparabilityReasonCode.FILTERING_MISMATCH: RefusalReasonCode.SOURCE_PROCESSING_MISMATCH,
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
        ),
        ComparabilityReasonCode.PHASE_SYSTEM_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
        ComparabilityReasonCode.PHASE_DEFINITION_MISMATCH: RefusalReasonCode.PHASE_METHOD_MISMATCH,
        ComparabilityReasonCode.PHASE_BOUNDARY_METHOD_MISMATCH: (
            RefusalReasonCode.PHASE_METHOD_MISMATCH
        ),
    }
    mapped_reasons: list[RefusalReasonCode] = []
    for code in result.reason_codes:
        try:
            reason = mapping.get(
                ComparabilityReasonCode(code), RefusalReasonCode.METRIC_DEFINITION_MISMATCH
            )
        except ValueError:
            reason = RefusalReasonCode.METRIC_DEFINITION_MISMATCH
        if reason not in mapped_reasons:
            mapped_reasons.append(reason)
    return _metric_refusal(
        blocked_claim,
        tuple(mapped_reasons) or (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
        result.missing_information or ("registered RES-65 metric comparability bridge",),
        observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


# Readable aliases keep the public surface operation-shaped without adding
# alternate scientific identities.
calculate_cmj_total_supported_force_metric = calculate_cmj_force_metric
calculate_cmj_power = calculate_cmj_power_metric
calculate_cmj_takeoff_velocity = project_cmj_takeoff_velocity
calculate_cmj_takeoff_velocity_scalar = project_cmj_takeoff_velocity
calculate_cmj_rsi_modified = calculate_cmj_rsi_mod
calculate_cmj_asymmetry = calculate_cmj_force_asymmetry


__all__ = [
    "RES65_SOFTWARE_VERSION",
    "CMJAsymmetryEquation",
    "CMJAsymmetryMetric",
    "CMJCompletedMetricResult",
    "CMJForceAsymmetryResult",
    "CMJForceMetric",
    "CMJForceMetricResult",
    "CMJMetricComparabilityRequest",
    "CMJMetricSupport",
    "CMJMetricSupportKind",
    "CMJPowerMetric",
    "CMJPowerResult",
    "CMJPowerSeries",
    "CMJRSIModNumerator",
    "CMJRSIModResult",
    "CMJTakeoffVelocityResult",
    "calculate_cmj_asymmetry",
    "calculate_cmj_force_asymmetry",
    "calculate_cmj_force_metric",
    "calculate_cmj_phase_force_asymmetry",
    "calculate_cmj_phase_force_metric",
    "calculate_cmj_phase_peak_total_supported_vertical_force",
    "calculate_cmj_phase_power_metric",
    "calculate_cmj_phase_time_mean_total_supported_vertical_force",
    "calculate_cmj_power",
    "calculate_cmj_power_metric",
    "calculate_cmj_rsi_mod",
    "calculate_cmj_rsi_modified",
    "calculate_cmj_takeoff_velocity",
    "calculate_cmj_takeoff_velocity_scalar",
    "calculate_cmj_total_supported_force_metric",
    "calculate_cmj_whole_movement_peak_total_supported_vertical_force",
    "calculate_cmj_whole_movement_time_mean_total_supported_vertical_force",
    "cmj_metric_ranking_key",
    "compare_cmj_metric_results",
    "project_cmj_takeoff_velocity",
    "refusal_for_cmj_metric_comparability",
    "refuse_unregistered_cmj_rfd",
]
