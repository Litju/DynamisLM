"""Versioned, source-bound CMJ phases and initial phase metrics.

RES-39 deliberately implements one sampled force-platform / supported-system
COM-velocity phase system.  The module does not define a universal CMJ phase
ontology and does not reinterpret the distinct yielding, eccentric, braking,
concentric, unweighting, or propulsion traditions as aliases.
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
from dynamislm.measurement.cmj.acquisition import TimebaseIdentity
from dynamislm.measurement.cmj.comparability import compare_cmj_measurement_identities
from dynamislm.measurement.cmj.events import (
    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD,
    CMJ_MOVEMENT_ONSET_EVENT_DEFINITION,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
    CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION,
    CMJEventDetectorParameters,
    CMJEventOccurrence,
)
from dynamislm.measurement.cmj.identity import CMJ_REGISTRY_VERSION, CMJMeasurementIdentity
from dynamislm.measurement.cmj.mechanics import (
    CMJIntegrationInterval,
    CMJMechanicalSystemContract,
    CMJMechanicsQuantity,
    InitialVelocityCondition,
    NetVerticalForceResult,
    QualifiedZeroVelocityReference,
    SupportedSystemComRelativeDisplacementResult,
    SupportedSystemComVelocityResult,
    integrate_net_vertical_impulse,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_BRAKING_DISPLACEMENT_CHANGE_MEASURAND,
    CMJ_BRAKING_DISPLACEMENT_CHANGE_METRIC,
    CMJ_BRAKING_DURATION_MEASURAND,
    CMJ_BRAKING_DURATION_METRIC,
    CMJ_BRAKING_NET_VERTICAL_IMPULSE_MEASURAND,
    CMJ_BRAKING_NET_VERTICAL_IMPULSE_METRIC,
    CMJ_BRAKING_PHASE_DEFINITION,
    CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD,
    CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY,
    CMJ_MECHANICS_SYSTEM_CONTRACT,
    CMJ_NET_VERTICAL_FORCE_OPERATION,
    CMJ_PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY_METHOD,
    CMJ_PHASE_COMPARABILITY_RULE,
    CMJ_PHASE_DURATION_OPERATION,
    CMJ_PHASE_NET_VERTICAL_IMPULSE_OPERATION,
    CMJ_PHASE_RELATIVE_DISPLACEMENT_CHANGE_OPERATION,
    CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION,
    CMJ_PROPULSION_DISPLACEMENT_CHANGE_MEASURAND,
    CMJ_PROPULSION_DISPLACEMENT_CHANGE_METRIC,
    CMJ_PROPULSION_DURATION_MEASURAND,
    CMJ_PROPULSION_DURATION_METRIC,
    CMJ_PROPULSION_NET_VERTICAL_IMPULSE_MEASURAND,
    CMJ_PROPULSION_NET_VERTICAL_IMPULSE_METRIC,
    CMJ_PROPULSION_PHASE_DEFINITION,
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION,
    CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_TRAPEZOIDAL_INTEGRATION_METHOD,
    CMJ_UNWEIGHTING_DURATION_MEASURAND,
    CMJ_UNWEIGHTING_DURATION_METRIC,
    CMJ_UNWEIGHTING_PHASE_DEFINITION,
    METER,
    NEWTON_SECOND,
    RES36_DECISION_EVENT_SEMANTICS,
    RES37_DECISION_DISPLACEMENT_REFERENCE,
    RES37_DECISION_IMPULSE_INTEGRATION,
    RES39_DECISION_PHASE_BOUNDARIES,
    RES39_DECISION_PHASE_COMPARABILITY_REFUSAL,
    RES39_DECISION_PHASE_METRICS,
    RES39_DECISION_PHASE_SYSTEM,
    SECOND,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    _derived_identity,
    _merge_provenance,
    _provenance_with_run,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    require_tuple,
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
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
)
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import (
    canonical_hash,
    canonical_json,
    from_canonical_json,
    register_serializable_type,
)

RES39_SOFTWARE_VERSION = "dynamislm-res39-1.0.0"
_UNCERTAINTY_NOTE = "RES-39 deterministic phase arithmetic; uncertainty is not assessed."
_PHASE_SAMPLE_SUPPORT_SEMANTICS = (
    "[start_index, end_index] endpoint samples are retained; adjacent phases may "
    "share a boundary sample; trapezoids are the intervals (start_index, end_index]"
)


class CMJPhaseLabel(StrEnum):
    """Labels computationally defined by the selected V1 system."""

    UNWEIGHTING = "UNWEIGHTING"
    BRAKING = "BRAKING"
    PROPULSION = "PROPULSION"


class CMJPhaseBoundaryKind(StrEnum):
    """Boundary roles retained without making cross-system aliases."""

    MOVEMENT_ONSET = "MOVEMENT_ONSET"
    PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY = "PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY"
    DIRECTION_CHANGE = "DIRECTION_CHANGE"
    PROPULSION_ONSET = "PROPULSION_ONSET"
    TAKEOFF = "TAKEOFF"


class CMJPhaseMetric(StrEnum):
    """The closed initial V1 phase-metric set."""

    UNWEIGHTING_DURATION = "UNWEIGHTING_DURATION"
    BRAKING_DURATION = "BRAKING_DURATION"
    PROPULSION_DURATION = "PROPULSION_DURATION"
    BRAKING_NET_VERTICAL_IMPULSE = "BRAKING_NET_VERTICAL_IMPULSE"
    PROPULSION_NET_VERTICAL_IMPULSE = "PROPULSION_NET_VERTICAL_IMPULSE"
    BRAKING_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE = (
        "BRAKING_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE"
    )
    PROPULSION_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE = (
        "PROPULSION_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE"
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseSystem:
    """A versioned phase-system identity and its closed V1 definitions."""

    reference: RegistryReference
    phase_definitions: tuple[RegistryReference, ...]
    landmark_methods: tuple[RegistryReference, ...]
    decision_reference: RegistryReference

    def __post_init__(self) -> None:
        if self.reference.stable_id != CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id:
            raise ValueError("phase system is not the registered CMJ V1 system")
        require_tuple(self.phase_definitions, "phase_definitions")
        require_tuple(self.landmark_methods, "landmark_methods")
        if self.phase_definitions != (
            CMJ_UNWEIGHTING_PHASE_DEFINITION,
            CMJ_BRAKING_PHASE_DEFINITION,
            CMJ_PROPULSION_PHASE_DEFINITION,
        ):
            raise ValueError("CMJ V1 phase definitions are not the registered closed set")
        if self.landmark_methods != (
            CMJ_PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY_METHOD,
            CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD,
        ):
            raise ValueError("CMJ V1 landmark methods are not the registered closed set")
        if self.decision_reference.stable_id != RES39_DECISION_PHASE_SYSTEM.stable_id:
            raise ValueError("phase system must cite the RES-39 phase-system decision")

    @property
    def version(self) -> str:
        return self.reference.identifier.version


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseDefinition:
    """A method-specific phase definition, not a universal label mapping."""

    reference: RegistryReference
    label: CMJPhaseLabel
    phase_system: RegistryReference
    start_boundary: CMJPhaseBoundaryKind
    end_boundary: CMJPhaseBoundaryKind
    definition_text: str

    def __post_init__(self) -> None:
        if self.reference.identifier.object_type != "phase-definition":
            raise ValueError("phase definition reference must have object_type phase-definition")
        if not isinstance(self.label, CMJPhaseLabel):
            raise ValueError("phase definition label must be a CMJPhaseLabel")
        if self.phase_system.stable_id != CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id:
            raise ValueError("phase definition must use the registered V1 phase system")
        if not isinstance(self.start_boundary, CMJPhaseBoundaryKind) or not isinstance(
            self.end_boundary, CMJPhaseBoundaryKind
        ):
            raise ValueError("phase definition boundaries must be registered boundary kinds")
        if not self.definition_text.strip():
            raise ValueError("phase definition text must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseSampleSupport:
    """Inclusive endpoint samples with one-time ownership of each trapezoid."""

    start_index: int
    end_index: int
    convention: RegistryReference = CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION
    semantics: str = _PHASE_SAMPLE_SUPPORT_SEMANTICS

    def __post_init__(self) -> None:
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("phase sample support indices must be integers")
        if self.start_index < 0 or self.end_index <= self.start_index:
            raise ValueError("phase sample support must have end_index greater than start_index")
        if self.convention.stable_id != CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION.stable_id:
            raise ValueError("phase sample support requires the registered V1 convention")
        if self.semantics != _PHASE_SAMPLE_SUPPORT_SEMANTICS:
            raise ValueError("phase sample support semantics are not the registered V1 convention")

    @property
    def interval_semantics(self) -> str:
        return self.semantics


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseBoundary:
    """One source-attached phase boundary or sampled landmark."""

    boundary_id: InstanceIdentifier
    kind: CMJPhaseBoundaryKind
    phase_system: RegistryReference
    method: RegistryReference
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_velocity_observation_id: InstanceIdentifier
    source_velocity_series_id: InstanceIdentifier
    source_timebase: SignalTimebase
    source_sample_count: int
    search_start_index: int
    search_end_index: int
    sample_index: int
    boundary_time_s: float
    velocity_m_per_s: float
    tie_policy: str
    velocity_threshold_policy: str
    interpolation_policy: str
    evidence_decision: RegistryReference
    provenance: Provenance
    source_event_id: InstanceIdentifier | None = None
    source_event_definition: RegistryReference | None = None
    source_event_method: RegistryReference | None = None
    source_event_parameters: str | None = None
    source_event_effective_threshold_n: float | None = None

    def __post_init__(self) -> None:
        if self.boundary_id.instance_type != "phase-boundary":
            raise ValueError("phase boundary ID must have instance_type phase-boundary")
        if not isinstance(self.kind, CMJPhaseBoundaryKind):
            raise ValueError("boundary kind must be a registered CMJPhaseBoundaryKind")
        if self.phase_system.stable_id != CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id:
            raise ValueError("boundary must use the registered V1 phase system")
        if self.method.identifier.object_type not in {
            "event-method",
            "phase-landmark-method",
            "phase-boundary-method",
        }:
            raise ValueError("boundary method is not a registered phase/event method")
        expected_method = {
            CMJPhaseBoundaryKind.MOVEMENT_ONSET: CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD.reference,
            CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY: (
                CMJ_PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY_METHOD
            ),
            CMJPhaseBoundaryKind.DIRECTION_CHANGE: (
                CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD
            ),
            CMJPhaseBoundaryKind.PROPULSION_ONSET: (
                CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD
            ),
            CMJPhaseBoundaryKind.TAKEOFF: CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD.reference,
        }[self.kind]
        if self.method.stable_id != expected_method.stable_id:
            raise ValueError("boundary method does not match its registered boundary kind")
        for field_name, value, expected_type in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
            ("source_velocity_observation_id", self.source_velocity_observation_id, "observation"),
            ("source_velocity_series_id", self.source_velocity_series_id, "signal"),
        ):
            if value.instance_type != expected_type:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("source measurement identity must be a measurement-identity")
        if not isinstance(self.source_timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("phase boundary requires a registered source timebase")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("source_sample_count must be a positive integer")
        for field_name, index_value in (
            ("search_start_index", self.search_start_index),
            ("search_end_index", self.search_end_index),
            ("sample_index", self.sample_index),
        ):
            if type(index_value) is not int or index_value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if not (
            self.search_start_index <= self.sample_index <= self.search_end_index
            and self.search_end_index < self.source_sample_count
        ):
            raise ValueError("boundary sample must lie inside its declared search support")
        if isinstance(self.source_timebase, ExplicitTimebase) and self.sample_index >= len(
            self.source_timebase.times_s
        ):
            raise ValueError("explicit timebase does not cover the boundary sample")
        if isinstance(self.source_timebase, RegularTimebase):
            expected_time = self.source_timebase.start_time_s + (
                self.sample_index / self.source_timebase.sample_rate_hz
            )
        else:
            expected_time = self.source_timebase.times_s[self.sample_index]
        if self.boundary_time_s != expected_time:
            raise ValueError("boundary time must be the exact source sample time")
        for field_name, numeric_value in (
            ("boundary_time_s", self.boundary_time_s),
            ("velocity_m_per_s", self.velocity_m_per_s),
        ):
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, int | float)
                or not math.isfinite(numeric_value)
            ):
                raise ValueError(f"{field_name} must be finite")
        for field_name, text_value in (
            ("tie_policy", self.tie_policy),
            ("velocity_threshold_policy", self.velocity_threshold_policy),
            ("interpolation_policy", self.interpolation_policy),
        ):
            if not text_value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.evidence_decision.identifier.object_type != "decision-record":
            raise ValueError("phase boundary evidence must be a decision record")
        event_backed = self.kind in {
            CMJPhaseBoundaryKind.MOVEMENT_ONSET,
            CMJPhaseBoundaryKind.TAKEOFF,
        }
        if event_backed and self.source_event_id is None:
            raise ValueError("sealed event phase boundaries must preserve their event occurrence")
        if not event_backed and self.source_event_id is not None:
            raise ValueError("derived phase landmarks cannot contain event occurrence metadata")
        if self.source_event_id is not None:
            if self.source_event_id.instance_type != "event-occurrence":
                raise ValueError("source_event_id must identify an event occurrence")
            if self.source_event_definition is None or self.source_event_method is None:
                raise ValueError("event-backed boundary must preserve event definition and method")
            if self.source_event_definition.identifier.object_type != "event-definition":
                raise ValueError("source event definition must be registered")
            if self.source_event_method.identifier.object_type != "event-method":
                raise ValueError("source event method must be registered")
            expected_event_definition = {
                CMJPhaseBoundaryKind.MOVEMENT_ONSET: CMJ_MOVEMENT_ONSET_EVENT_DEFINITION.reference,
                CMJPhaseBoundaryKind.TAKEOFF: CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION.reference,
            }[self.kind]
            expected_event_method = {
                CMJPhaseBoundaryKind.MOVEMENT_ONSET: (
                    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD.reference
                ),
                CMJPhaseBoundaryKind.TAKEOFF: CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD.reference,
            }[self.kind]
            if self.source_event_definition.stable_id != expected_event_definition.stable_id:
                raise ValueError("source event definition does not match phase boundary kind")
            if self.source_event_method.stable_id != expected_event_method.stable_id:
                raise ValueError("source event method does not match phase boundary kind")
            if self.source_event_parameters is None or not self.source_event_parameters.strip():
                raise ValueError("event-backed boundary must preserve detector parameters")
            if self.source_event_effective_threshold_n is None or not math.isfinite(
                self.source_event_effective_threshold_n
            ):
                raise ValueError("event-backed boundary must preserve its effective threshold")
        elif any(
            value is not None
            for value in (
                self.source_event_definition,
                self.source_event_method,
                self.source_event_parameters,
                self.source_event_effective_threshold_n,
            )
        ):
            raise ValueError("non-event phase landmark cannot contain event metadata")
        matching_runs = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_entity_id == self.boundary_id
        )
        if len(matching_runs) != 1:
            raise ValueError("phase boundary must preserve exactly one output processing run")
        if matching_runs[0].method != self.method:
            raise ValueError("phase boundary processing method must match its method")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseOccurrence:
    """A complete V1 phase occurrence with source and boundary provenance."""

    occurrence_id: InstanceIdentifier
    phase_system: RegistryReference
    phase_definition: RegistryReference
    source_context: ObservationContext
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity: CMJMeasurementIdentity
    source_velocity_observation_id: InstanceIdentifier
    source_velocity_series_id: InstanceIdentifier
    source_velocity_measurement_identity: CMJMeasurementIdentity
    source_velocity_operation: RegistryReference
    source_velocity_integration_method: RegistryReference
    source_velocity_integration_interval: CMJIntegrationInterval
    source_velocity_initial_condition: QualifiedZeroVelocityReference
    source_velocity_version: VersionIdentity
    source_velocity_processing_parameters: tuple[MetadataEntry, ...]
    source_velocity_filtering: tuple[RegistryReference, ...]
    source_velocity_source_signal_ids: tuple[InstanceIdentifier, ...]
    source_velocity_source_observation_ids: tuple[InstanceIdentifier, ...]
    source_velocity_source_measurement_identity_ids: tuple[ScientificIdentifier, ...]
    source_system_contract: CMJMechanicalSystemContract
    start_boundary: CMJPhaseBoundary
    end_boundary: CMJPhaseBoundary
    start_time_s: float
    end_time_s: float
    sample_support: CMJPhaseSampleSupport
    boundary_convention: RegistryReference
    interpolation_policy: str
    velocity_threshold_policy: str
    source_event_ids: tuple[InstanceIdentifier, ...]
    evidence_decision: RegistryReference
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.occurrence_id.instance_type != "phase-occurrence":
            raise ValueError("phase occurrence ID must have instance_type phase-occurrence")
        if self.phase_system.stable_id != CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id:
            raise ValueError("phase occurrence must use the registered V1 phase system")
        phase_definition = _phase_definition_for_reference(self.phase_definition)
        if phase_definition is None:
            raise ValueError("phase occurrence definition is not registered")
        if phase_definition.phase_system.stable_id != self.phase_system.stable_id:
            raise ValueError("phase occurrence definition/system identity does not match")
        expected_kinds = {
            CMJPhaseLabel.UNWEIGHTING: (
                CMJPhaseBoundaryKind.MOVEMENT_ONSET,
                CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY,
            ),
            CMJPhaseLabel.BRAKING: (
                CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY,
                CMJPhaseBoundaryKind.DIRECTION_CHANGE,
            ),
            CMJPhaseLabel.PROPULSION: (
                CMJPhaseBoundaryKind.PROPULSION_ONSET,
                CMJPhaseBoundaryKind.TAKEOFF,
            ),
        }[phase_definition.label]
        if (self.start_boundary.kind, self.end_boundary.kind) != expected_kinds:
            raise ValueError("phase occurrence boundaries do not match its registered definition")
        if self.source_observation_id.instance_type != "observation":
            raise ValueError("phase source observation must identify an observation")
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("phase source signal must identify a signal")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("phase source artifact must identify an artifact")
        if self.source_acquisition_id.instance_type != "acquisition":
            raise ValueError("phase source acquisition must identify an acquisition")
        if self.source_velocity_observation_id.instance_type != "observation":
            raise ValueError("phase velocity source must identify an observation")
        if self.source_velocity_series_id.instance_type != "signal":
            raise ValueError("phase velocity series must identify a signal")
        if not isinstance(self.source_measurement_identity, CMJMeasurementIdentity):
            raise ValueError("phase source identity must be a CMJMeasurementIdentity")
        if not isinstance(self.source_velocity_measurement_identity, CMJMeasurementIdentity):
            raise ValueError("phase velocity identity must be a CMJMeasurementIdentity")
        if (
            self.source_measurement_identity.identity_id
            != self.start_boundary.source_measurement_identity_id
        ):
            raise ValueError("phase source identity does not match its start boundary")
        if (
            self.source_measurement_identity.identity_id
            != self.end_boundary.source_measurement_identity_id
        ):
            raise ValueError("phase source identity does not match its end boundary")
        if self.source_velocity_measurement_identity.processing.registered_operation is None:
            raise ValueError("phase velocity identity must preserve its registered operation")
        if (
            self.source_velocity_measurement_identity.processing.registered_operation.stable_id
            != CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION.stable_id
        ):
            raise ValueError("phase velocity identity must be the supported-system COM velocity")
        if (
            self.source_velocity_operation.stable_id
            != CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION.stable_id
        ):
            raise ValueError("phase velocity operation is not registered")
        if (
            self.source_velocity_measurement_identity.processing.registered_operation
            != self.source_velocity_operation
        ):
            raise ValueError("phase velocity operation does not match its source identity")
        if (
            self.source_velocity_integration_method.stable_id
            != CMJ_TRAPEZOIDAL_INTEGRATION_METHOD.stable_id
        ):
            raise ValueError("phase velocity integration method is not registered")
        if not isinstance(self.source_velocity_integration_interval, CMJIntegrationInterval):
            raise ValueError("phase velocity interval must be a registered integration interval")
        if (
            self.source_velocity_integration_interval.integration_method.stable_id
            != self.source_velocity_integration_method.stable_id
        ):
            raise ValueError("phase velocity interval must preserve its integration method")
        if not isinstance(self.source_velocity_initial_condition, QualifiedZeroVelocityReference):
            raise ValueError("phase occurrence requires a qualified velocity reference")
        if not self.source_velocity_initial_condition.is_authorized:
            raise ValueError("phase occurrence requires an authorized velocity reference")
        if not self.source_system_contract.is_authorized:
            raise ValueError("phase occurrence requires an authorized supported-system contract")
        if self.source_velocity_version != self.source_velocity_measurement_identity.version:
            raise ValueError("phase velocity version does not match its source identity")
        if (
            self.source_velocity_processing_parameters
            != self.source_velocity_measurement_identity.processing.method_parameters
        ):
            raise ValueError("phase velocity parameters do not match its source identity")
        if (
            self.source_velocity_filtering
            != self.source_velocity_measurement_identity.processing.filtering
        ):
            raise ValueError("phase velocity filtering does not match its source identity")
        require_tuple(
            self.source_velocity_processing_parameters, "source_velocity_processing_parameters"
        )
        require_tuple(self.source_velocity_filtering, "source_velocity_filtering")
        require_tuple(self.source_velocity_source_signal_ids, "source_velocity_source_signal_ids")
        require_tuple(
            self.source_velocity_source_observation_ids,
            "source_velocity_source_observation_ids",
        )
        require_tuple(
            self.source_velocity_source_measurement_identity_ids,
            "source_velocity_source_measurement_identity_ids",
        )
        if any(item.instance_type != "signal" for item in self.source_velocity_source_signal_ids):
            raise ValueError("source_velocity_source_signal_ids must identify signals")
        if any(
            item.instance_type != "observation"
            for item in self.source_velocity_source_observation_ids
        ):
            raise ValueError("source_velocity_source_observation_ids must identify observations")
        if any(
            item.object_type != "measurement-identity"
            for item in self.source_velocity_source_measurement_identity_ids
        ):
            raise ValueError(
                "source_velocity_source_measurement_identity_ids must identify "
                "measurement identities"
            )
        if self.source_velocity_integration_interval.source_signal_id not in (
            self.source_velocity_source_signal_ids
        ):
            raise ValueError("phase velocity interval must preserve its source signal")
        require_tuple(self.source_event_ids, "source_event_ids")
        if any(event_id.instance_type != "event-occurrence" for event_id in self.source_event_ids):
            raise ValueError("source_event_ids must identify event occurrences")
        event_runs = {
            run.output_entity_id: run
            for run in self.provenance.processing_runs
            if run.method.identifier.object_type == "event-method"
            and run.output_entity_id.instance_type == "event-occurrence"
        }
        expected_event_definitions = {
            CMJ_MOVEMENT_ONSET_EVENT_DEFINITION.reference.stable_id,
            CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION.reference.stable_id,
        }
        preserved_event_definitions = {
            entry.value
            for run in event_runs.values()
            for entry in run.parameters
            if entry.key == "event_definition" and isinstance(entry.value, str)
        }
        if len(event_runs) != len(expected_event_definitions) or (
            preserved_event_definitions != expected_event_definitions
        ):
            raise ValueError(
                "phase occurrence must preserve movement-onset and takeoff event processing runs"
            )
        for event_run in event_runs.values():
            detector_parameters = next(
                (
                    entry.value
                    for entry in event_run.parameters
                    if entry.key == "detector_parameters"
                ),
                None,
            )
            if not isinstance(detector_parameters, str) or not detector_parameters.strip():
                raise ValueError("source event processing run must preserve detector parameters")
            try:
                from_canonical_json(detector_parameters, CMJEventDetectorParameters)
            except (TypeError, ValueError):
                raise ValueError(
                    "source event processing run detector parameters must be canonical"
                ) from None
        for event_id in self.source_event_ids:
            if event_id not in event_runs:
                raise ValueError(
                    "phase occurrence must preserve the processing run for every source event"
                )
        for boundary in (self.start_boundary, self.end_boundary):
            if (
                boundary.phase_system.stable_id != self.phase_system.stable_id
                or boundary.source_observation_id != self.source_observation_id
                or boundary.source_signal_id != self.source_signal_id
                or boundary.source_artifact_id != self.source_artifact_id
                or boundary.source_acquisition_id != self.source_acquisition_id
                or boundary.source_measurement_identity_id
                != self.source_measurement_identity.identity_id
                or boundary.source_velocity_observation_id != self.source_velocity_observation_id
                or boundary.source_velocity_series_id != self.source_velocity_series_id
            ):
                raise ValueError("phase boundary source identity does not match occurrence")
        if self.start_boundary.sample_index != self.sample_support.start_index:
            raise ValueError("phase start boundary does not match sample support")
        if self.end_boundary.sample_index != self.sample_support.end_index:
            raise ValueError("phase end boundary does not match sample support")
        if (
            self.boundary_convention.stable_id
            != CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION.stable_id
        ):
            raise ValueError("phase occurrence boundary convention is not registered")
        if self.sample_support.convention.stable_id != self.boundary_convention.stable_id:
            raise ValueError("phase sample support and boundary convention must agree")
        if (
            self.start_time_s != self.start_boundary.boundary_time_s
            or self.end_time_s != self.end_boundary.boundary_time_s
        ):
            raise ValueError("phase times must equal exact boundary times")
        if not math.isfinite(self.start_time_s) or not math.isfinite(self.end_time_s):
            raise ValueError("phase times must be finite")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("phase interval must have positive duration")
        if self.interpolation_policy != "none; exact source samples only":
            raise ValueError("phase interpolation policy is not the registered V1 policy")
        if self.velocity_threshold_policy != "none; strict positive rule is > 0.0 m/s":
            raise ValueError("phase velocity threshold policy is not the registered V1 policy")
        if self.evidence_decision.identifier.object_type != "decision-record":
            raise ValueError("phase occurrence evidence must be a decision record")
        matching_runs = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_entity_id == self.occurrence_id
        )
        if len(matching_runs) != 1 or matching_runs[0].method != self.phase_system:
            raise ValueError("phase occurrence must preserve one phase-system processing run")

    @property
    def label(self) -> CMJPhaseLabel:
        definition = _phase_definition_for_reference(self.phase_definition)
        if definition is None:
            raise ValueError("phase definition is not registered")
        return definition.label

    @property
    def source_measurement_identity_id(self) -> ScientificIdentifier:
        return self.source_measurement_identity.identity_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseMetricResult:
    """A registered numerical phase metric retaining its phase occurrence."""

    observation: ScientificMeasurementObservation
    metric: CMJPhaseMetric
    phase_occurrence: CMJPhaseOccurrence
    source_mechanics_observation_id: InstanceIdentifier
    source_mechanics_series_id: InstanceIdentifier
    source_mechanics_quantity: CMJMechanicsQuantity
    source_mechanics_operation: RegistryReference
    source_timebase: SignalTimebase
    source_system_contract: CMJMechanicalSystemContract
    source_integration_interval: CMJIntegrationInterval | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, CMJPhaseMetric):
            raise ValueError("metric must be a registered CMJPhaseMetric")
        expected_phase, measurand, metric_ref, operation, unit = _phase_metric_spec(self.metric)
        if self.phase_occurrence.label is not expected_phase:
            raise ValueError("phase metric does not match the phase occurrence")
        identity = self.observation.identity
        if not isinstance(identity, CMJMeasurementIdentity):
            raise ValueError("phase metric observation requires a CMJ measurement identity")
        if identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
            raise ValueError("phase metric must retain the supported-system construct")
        if identity.semantic.measurand.stable_id != measurand.stable_id:
            raise ValueError("phase metric has the wrong measurand")
        if identity.semantic.metric_definition.stable_id != metric_ref.stable_id:
            raise ValueError("phase metric has the wrong metric definition")
        if (
            identity.processing.registered_operation is None
            or identity.processing.registered_operation.stable_id != operation.stable_id
        ):
            raise ValueError("phase metric has the wrong operation")
        if identity.processing.phase_definitions != (self.phase_occurrence.phase_definition,):
            raise ValueError("phase metric must retain its phase definition")
        if (
            self.observation.result.unit is None
            or self.observation.result.unit.identifier.stable_id != unit.identifier.stable_id
        ):
            raise ValueError("phase metric has the wrong unit")
        if not isinstance(self.observation.result.value, ScalarValue) or isinstance(
            self.observation.result.value.value, bool
        ):
            raise ValueError("phase metric must contain one numeric scalar")
        if (
            self.observation.result.classification.value_origin
            is not ValueOrigin.DERIVED_MECHANICAL_QUANTITY
        ):
            raise ValueError("phase metric must be a derived mechanical quantity")
        if self.observation.result.classification.scientific_roles != ():
            raise ValueError("phase metric scientific roles must remain explicitly empty")
        if self.source_mechanics_observation_id.instance_type != "observation":
            raise ValueError("phase metric source mechanics must identify an observation")
        if self.source_mechanics_series_id.instance_type != "signal":
            raise ValueError("phase metric source mechanics must identify a signal")
        if self.source_mechanics_operation.identifier.object_type != "registered-operation":
            raise ValueError("phase metric source mechanics must preserve its operation")
        expected_source_operation = {
            CMJMechanicsQuantity.NET_VERTICAL_FORCE: CMJ_NET_VERTICAL_FORCE_OPERATION,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY: (
                CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION
            ),
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT: (
                CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION
            ),
        }.get(self.source_mechanics_quantity)
        if (
            expected_source_operation is None
            or self.source_mechanics_operation.stable_id != expected_source_operation.stable_id
        ):
            raise ValueError("phase metric source operation does not match its quantity")
        if self.source_system_contract != self.phase_occurrence.source_system_contract:
            raise ValueError("phase metric system contract does not match its phase")
        if self.source_timebase != self.phase_occurrence.start_boundary.source_timebase:
            raise ValueError("phase metric timebase does not match its phase")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if parameters.get("phase_occurrence_id") != self.phase_occurrence.occurrence_id.qualified:
            raise ValueError("phase metric must preserve phase occurrence identity")
        if (
            parameters.get("source_mechanics_series_id")
            != self.source_mechanics_series_id.qualified
        ):
            raise ValueError("phase metric must preserve mechanics series identity")
        if (
            parameters.get("source_mechanics_operation")
            != self.source_mechanics_operation.stable_id
        ):
            raise ValueError("phase metric must preserve mechanics operation identity")
        if self.metric in {
            CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE,
            CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
        }:
            if self.source_integration_interval is None:
                raise ValueError("phase impulse must preserve its integration interval")
            if self.source_integration_interval.source_signal_id != self.source_mechanics_series_id:
                raise ValueError("phase impulse interval must identify its source mechanics series")
            if (
                self.source_integration_interval.boundary_convention.stable_id
                != CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY.stable_id
            ):
                raise ValueError("phase impulse must use the RES-37 integration convention")
        elif self.source_integration_interval is not None:
            raise ValueError("non-impulse phase metrics must not contain an integration interval")
        matching_runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(matching_runs) != 1 or matching_runs[0].method != operation:
            raise ValueError("phase metric must preserve one matching output processing run")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("phase metric is not numeric")
        return float(value.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJPhaseComparabilityRequest:
    """Claim-relative request retaining two phase metric occurrences."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("phase comparability requires two distinct observations")
        if not self.claim.strip():
            raise ValueError("phase comparability claim must not be empty")
        require_tuple(self.requested_transformations, "requested_transformations")


CMJ_UNWEIGHTING_PHASE_V1 = CMJPhaseDefinition(
    reference=CMJ_UNWEIGHTING_PHASE_DEFINITION,
    label=CMJPhaseLabel.UNWEIGHTING,
    phase_system=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    start_boundary=CMJPhaseBoundaryKind.MOVEMENT_ONSET,
    end_boundary=CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY,
    definition_text="movement onset through the peak negative supported-system COM velocity sample",
)
CMJ_BRAKING_PHASE_V1 = CMJPhaseDefinition(
    reference=CMJ_BRAKING_PHASE_DEFINITION,
    label=CMJPhaseLabel.BRAKING,
    phase_system=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    start_boundary=CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY,
    end_boundary=CMJPhaseBoundaryKind.DIRECTION_CHANGE,
    definition_text=(
        "peak negative supported-system COM velocity through the first strictly "
        "positive velocity sample"
    ),
)
CMJ_PROPULSION_PHASE_V1 = CMJPhaseDefinition(
    reference=CMJ_PROPULSION_PHASE_DEFINITION,
    label=CMJPhaseLabel.PROPULSION,
    phase_system=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    start_boundary=CMJPhaseBoundaryKind.PROPULSION_ONSET,
    end_boundary=CMJPhaseBoundaryKind.TAKEOFF,
    definition_text="the first strictly positive velocity sample through takeoff/contact loss",
)
CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_SPEC = CMJPhaseSystem(
    reference=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    phase_definitions=(
        CMJ_UNWEIGHTING_PHASE_DEFINITION,
        CMJ_BRAKING_PHASE_DEFINITION,
        CMJ_PROPULSION_PHASE_DEFINITION,
    ),
    landmark_methods=(
        CMJ_PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY_METHOD,
        CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD,
    ),
    decision_reference=RES39_DECISION_PHASE_SYSTEM,
)
CMJ_PHASE_SYSTEM_V1 = CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_SPEC
CMJ_PHASE_DEFINITIONS = (
    CMJ_UNWEIGHTING_PHASE_V1,
    CMJ_BRAKING_PHASE_V1,
    CMJ_PROPULSION_PHASE_V1,
)


def _phase_definition_for_reference(reference: RegistryReference) -> CMJPhaseDefinition | None:
    return next(
        (definition for definition in CMJ_PHASE_DEFINITIONS if definition.reference == reference),
        None,
    )


def _finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _phase_refusal(
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    reason_values = tuple(code.value for code in reason_codes)
    digest = canonical_hash(
        {
            "blocked_claim": blocked_claim,
            "reason_codes": reason_values,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res39-phase:{digest}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=reason_values,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "valid RES-36 movement-onset, takeoff, and landing events remain "
            "independently describable",
            "valid RES-37 force, velocity, displacement, and jump-height inputs "
            "remain independently describable",
            "no athlete-only phase or unregistered power/RFD/aggregation claim is emitted",
        ),
        evidence_references=(RES39_DECISION_PHASE_SYSTEM, RES39_DECISION_PHASE_BOUNDARIES),
        observation_ids=observation_ids,
    )


def _time_at(timebase: SignalTimebase, sample_index: int) -> float:
    if isinstance(timebase, RegularTimebase):
        return timebase.start_time_s + sample_index / timebase.sample_rate_hz
    if isinstance(timebase, ExplicitTimebase):
        if sample_index >= len(timebase.times_s):
            raise ValueError("explicit timebase does not cover the requested sample")
        return timebase.times_s[sample_index]
    raise ValueError("a registered regular or explicit timebase is required")


def _velocity_sample(velocity: SupportedSystemComVelocityResult, sample_index: int) -> float:
    offset = sample_index - velocity.series.sample_start_index
    if offset < 0 or offset >= len(velocity.series.samples):
        raise ValueError("requested sample lies outside velocity series support")
    return velocity.series.samples[offset]


def _provenance_has_entity(provenance: Provenance, identifier: InstanceIdentifier) -> bool:
    qualified = identifier.qualified
    return qualified in {edge.from_id for edge in provenance.lineage_edges} | {
        run.output_entity_id.qualified for run in provenance.processing_runs
    }


def _phase_source_observation_ids(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
) -> tuple[InstanceIdentifier, ...]:
    return _unique(
        (
            velocity.observation.observation_id,
            movement_onset.source_observation_id,
            takeoff.source_observation_id,
        )
    )


def _phase_source_provenance(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
) -> Provenance:
    return _merge_provenance(
        _merge_provenance(
            velocity.observation.provenance,
            movement_onset.provenance,
        ),
        takeoff.provenance,
    )


def _add_entity_edges(
    provenance: Provenance,
    *,
    processing_run_id: InstanceIdentifier,
    entity_ids: tuple[InstanceIdentifier, ...],
) -> Provenance:
    edges = list(provenance.lineage_edges)
    for entity_id in entity_ids:
        edge = LineageEdge(
            entity_id.qualified,
            processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    return replace(provenance, lineage_edges=tuple(edges))


def _validate_phase_inputs(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    claim: str,
) -> RefusalResult | None:
    candidate_ids: list[InstanceIdentifier] = []
    if isinstance(velocity, SupportedSystemComVelocityResult):
        candidate_ids.append(velocity.observation.observation_id)
    if isinstance(movement_onset, CMJEventOccurrence):
        candidate_ids.append(movement_onset.source_observation_id)
    if isinstance(takeoff, CMJEventOccurrence):
        candidate_ids.append(takeoff.source_observation_id)
    observation_ids = _unique(tuple(candidate_ids))
    if not isinstance(velocity, SupportedSystemComVelocityResult):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.VELOCITY_AUTHORITY_REQUIRED,),
            ("RES-46-qualified SupportedSystemComVelocityResult",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not isinstance(movement_onset, CMJEventOccurrence) or not isinstance(
        takeoff, CMJEventOccurrence
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("exact RES-36 movement-onset and takeoff occurrences",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not velocity.initial_velocity_condition.is_authorized:
        return _phase_refusal(
            claim,
            (RefusalReasonCode.VELOCITY_AUTHORITY_REQUIRED,),
            ("adjudicated RES-46 QualifiedZeroVelocityReference",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not velocity.system_contract.is_authorized:
        return _phase_refusal(
            claim,
            (RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED,),
            ("authorized RES-37 supported-system contract",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        movement_onset.definition != CMJ_MOVEMENT_ONSET_EVENT_DEFINITION
        or movement_onset.detector_method != CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD
        or takeoff.definition != CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION
        or takeoff.detector_method != CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_METHOD_MISMATCH,),
            ("sealed RES-36 movement-onset and takeoff detector identities",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if (
        movement_onset.source_observation_id != takeoff.source_observation_id
        or movement_onset.source_signal_id != takeoff.source_signal_id
        or movement_onset.source_artifact_id != takeoff.source_artifact_id
        or movement_onset.source_acquisition_id != takeoff.source_acquisition_id
        or movement_onset.source_measurement_identity != takeoff.source_measurement_identity
        or movement_onset.source_timebase != takeoff.source_timebase
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("movement-onset and takeoff from one exact source observation/timebase",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    raw_identity = movement_onset.source_measurement_identity
    if (
        movement_onset.source_observation_id not in velocity.series.source_observation_ids
        and not _provenance_has_entity(
            velocity.observation.provenance, movement_onset.source_observation_id
        )
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("velocity provenance linked to the exact movement-onset source observation",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        movement_onset.source_signal_id
        not in (velocity.series.series_id, *velocity.series.source_signal_ids)
        or movement_onset.source_artifact_id not in velocity.series.source_artifact_ids
        or movement_onset.source_acquisition_id
        not in tuple(item.acquisition_id for item in velocity.observation.provenance.acquisitions)
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            (
                "velocity series/provenance linked to the exact source signal, "
                "artifact, and acquisition",
            ),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if raw_identity.identity_id not in velocity.series.source_measurement_identity_ids and not any(
        entry.value == raw_identity.identity_id.stable_id
        for run in velocity.observation.provenance.processing_runs
        for entry in run.parameters
        if entry.key in {"source_identity_ids", "source_measurement_identity_ids"}
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("velocity processing lineage linked to the exact source measurement identity",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if velocity.series.timebase != movement_onset.source_timebase:
        return _phase_refusal(
            claim,
            (RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,),
            ("velocity and sealed event occurrences with the exact same timebase",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if velocity.series.source_sample_count != movement_onset.source_sample_count:
        return _phase_refusal(
            claim,
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            ("velocity and event occurrences with the same source sample support",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not (
        movement_onset.sample_index < takeoff.sample_index
        and velocity.series.sample_start_index <= movement_onset.sample_index
        and takeoff.sample_index < velocity.series.sample_start_index + len(velocity.series.samples)
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("movement-onset and takeoff inside the velocity series in chronological order",),
            observation_ids=observation_ids,
        )
    if (
        isinstance(velocity.series.timebase, ExplicitTimebase)
        and len(velocity.series.timebase.times_s) != velocity.series.source_sample_count
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.INVALID_TIMEBASE,),
            ("explicit timestamps covering the complete source sample support",),
            observation_ids=observation_ids,
        )
    return None


def _validate_phase_system(
    phase_system: RegistryReference,
    *,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult | None:
    if (
        not isinstance(phase_system, RegistryReference)
        or phase_system.stable_id != CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SYSTEM_NOT_REGISTERED,),
            (CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id,),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    return None


def _boundary_provenance(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    boundary_id: InstanceIdentifier,
    method: RegistryReference,
    kind: CMJPhaseBoundaryKind,
    search_start_index: int,
    search_end_index: int,
    sample_index: int,
    tie_policy: str,
    velocity_threshold_policy: str,
    interpolation_policy: str,
    evidence_decision: RegistryReference,
    source_event: CMJEventOccurrence | None,
) -> Provenance:
    base = _phase_source_provenance(velocity, movement_onset, takeoff)
    source_observation_ids = _phase_source_observation_ids(velocity, movement_onset, takeoff)
    source_acquisition_ids = tuple(
        sorted((item.acquisition_id for item in base.acquisitions), key=lambda item: item.qualified)
    )
    parameters = (
        MetadataEntry("phase_system", CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id),
        MetadataEntry("boundary_kind", kind.value),
        MetadataEntry("boundary_method", method.stable_id),
        MetadataEntry("search_start_index", search_start_index),
        MetadataEntry("search_end_index", search_end_index),
        MetadataEntry("selected_sample_index", sample_index),
        MetadataEntry("tie_policy", tie_policy),
        MetadataEntry("velocity_threshold_policy", velocity_threshold_policy),
        MetadataEntry("interpolation_policy", interpolation_policy),
        MetadataEntry(
            "source_velocity_observation_id", velocity.observation.observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", velocity.series.series_id.qualified),
        MetadataEntry("source_timebase", canonical_json(velocity.series.timebase)),
        MetadataEntry("source_system_contract", canonical_json(velocity.system_contract)),
        MetadataEntry(
            "source_event_id",
            source_event.occurrence_id.qualified if source_event is not None else None,
        ),
        MetadataEntry(
            "source_event_definition",
            source_event.definition.reference.stable_id if source_event is not None else None,
        ),
        MetadataEntry(
            "source_event_method",
            source_event.detector_method.reference.stable_id if source_event is not None else None,
        ),
        MetadataEntry(
            "source_event_parameters",
            canonical_json(source_event.detector_parameters) if source_event is not None else None,
        ),
        MetadataEntry(
            "source_event_effective_threshold_n",
            source_event.effective_threshold_n if source_event is not None else None,
        ),
    )
    digest = canonical_hash(
        {
            "boundary_id": boundary_id.qualified,
            "method": method.stable_id,
            "parameters": parameters,
            "sample_index": sample_index,
        }
    ).removeprefix("sha256:")[:24]
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-phase-boundary:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=method,
        parameters=parameters,
        software_version=RES39_SOFTWARE_VERSION,
        output_entity_id=boundary_id,
    )
    evidence = EvidenceReference(evidence_decision, "registered RES-39 phase-boundary decision")
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=boundary_id,
        source_observation_ids=source_observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        supported_by=(evidence_decision, RES39_DECISION_PHASE_SYSTEM),
        evidence_references=(evidence,),
        recorded_at=base.recorded_at,
    )
    return _add_entity_edges(
        provenance,
        processing_run_id=run.processing_run_id,
        entity_ids=_unique(
            (
                velocity.observation.observation_id,
                velocity.series.series_id,
                movement_onset.occurrence_id,
                takeoff.occurrence_id,
            )
        ),
    )


def _make_boundary(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    kind: CMJPhaseBoundaryKind,
    method: RegistryReference,
    search_start_index: int,
    search_end_index: int,
    sample_index: int,
    tie_policy: str,
    velocity_threshold_policy: str,
    interpolation_policy: str,
    evidence_decision: RegistryReference,
    source_event: CMJEventOccurrence | None = None,
) -> CMJPhaseBoundary:
    boundary_digest = canonical_hash(
        {
            "phase_system": CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
            "boundary_kind": kind,
            "method": method,
            "source_velocity_observation": velocity.observation.observation_id,
            "source_velocity_series": velocity.series.series_id,
            "search_start_index": search_start_index,
            "search_end_index": search_end_index,
            "sample_index": sample_index,
            "tie_policy": tie_policy,
            "velocity_threshold_policy": velocity_threshold_policy,
            "interpolation_policy": interpolation_policy,
            "source_event_id": source_event.occurrence_id if source_event is not None else None,
            "source_event_definition": (
                source_event.definition.reference if source_event is not None else None
            ),
            "source_event_method": (
                source_event.detector_method.reference if source_event is not None else None
            ),
            "source_event_parameters": (
                canonical_json(source_event.detector_parameters)
                if source_event is not None
                else None
            ),
            "source_event_effective_threshold_n": (
                source_event.effective_threshold_n if source_event is not None else None
            ),
        }
    ).removeprefix("sha256:")[:24]
    boundary_id = InstanceIdentifier("phase-boundary", f"cmj-phase-boundary:{boundary_digest}")
    provenance = _boundary_provenance(
        velocity,
        movement_onset,
        takeoff,
        boundary_id=boundary_id,
        method=method,
        kind=kind,
        search_start_index=search_start_index,
        search_end_index=search_end_index,
        sample_index=sample_index,
        tie_policy=tie_policy,
        velocity_threshold_policy=velocity_threshold_policy,
        interpolation_policy=interpolation_policy,
        evidence_decision=evidence_decision,
        source_event=source_event,
    )
    return CMJPhaseBoundary(
        boundary_id=boundary_id,
        kind=kind,
        phase_system=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
        method=method,
        source_observation_id=movement_onset.source_observation_id,
        source_signal_id=movement_onset.source_signal_id,
        source_artifact_id=movement_onset.source_artifact_id,
        source_acquisition_id=movement_onset.source_acquisition_id,
        source_measurement_identity_id=movement_onset.source_measurement_identity.identity_id,
        source_velocity_observation_id=velocity.observation.observation_id,
        source_velocity_series_id=velocity.series.series_id,
        source_timebase=velocity.series.timebase,
        source_sample_count=velocity.series.source_sample_count,
        search_start_index=search_start_index,
        search_end_index=search_end_index,
        sample_index=sample_index,
        boundary_time_s=_time_at(velocity.series.timebase, sample_index),
        velocity_m_per_s=_velocity_sample(velocity, sample_index),
        tie_policy=tie_policy,
        velocity_threshold_policy=velocity_threshold_policy,
        interpolation_policy=interpolation_policy,
        evidence_decision=evidence_decision,
        provenance=provenance,
        source_event_id=source_event.occurrence_id if source_event is not None else None,
        source_event_definition=source_event.definition.reference
        if source_event is not None
        else None,
        source_event_method=source_event.detector_method.reference
        if source_event is not None
        else None,
        source_event_parameters=canonical_json(source_event.detector_parameters)
        if source_event is not None
        else None,
        source_event_effective_threshold_n=source_event.effective_threshold_n
        if source_event is not None
        else None,
    )


def detect_peak_negative_supported_system_com_velocity(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    phase_system: RegistryReference = CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
) -> CMJPhaseBoundary | RefusalResult:
    """Select the earliest tied minimum velocity sample from onset through takeoff."""

    claim = "detect RES-39 peak negative supported-system COM velocity"
    observation_ids = _unique(
        (
            velocity.observation.observation_id,
            movement_onset.source_observation_id,
            takeoff.source_observation_id,
        )
    )
    system_refusal = _validate_phase_system(
        phase_system, claim=claim, observation_ids=observation_ids
    )
    if system_refusal is not None:
        return system_refusal
    input_refusal = _validate_phase_inputs(velocity, movement_onset, takeoff, claim=claim)
    if input_refusal is not None:
        return input_refusal
    values = tuple(
        (index, _velocity_sample(velocity, index))
        for index in range(movement_onset.sample_index, takeoff.sample_index + 1)
    )
    minimum = min(value for _, value in values)
    if minimum >= 0.0:
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PEAK_NEGATIVE_VELOCITY_REQUIRED,),
            ("a strictly negative velocity minimum between movement onset and takeoff",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    selected_index = next(index for index, value in values if value == minimum)
    return _make_boundary(
        velocity,
        movement_onset,
        takeoff,
        kind=CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY,
        method=CMJ_PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY_METHOD,
        search_start_index=movement_onset.sample_index,
        search_end_index=takeoff.sample_index,
        sample_index=selected_index,
        tie_policy="earliest source sample among tied minimum velocity values",
        velocity_threshold_policy="none; minimum is selected without a positive threshold",
        interpolation_policy="none; exact source sample only",
        evidence_decision=RES39_DECISION_PHASE_BOUNDARIES,
    )


def detect_cmj_direction_change_boundary(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    peak_negative_velocity: CMJPhaseBoundary | None = None,
    *,
    phase_system: RegistryReference = CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
) -> CMJPhaseBoundary | RefusalResult:
    """Select the first strictly positive velocity sample after the minimum."""

    claim = "detect RES-39 direction-change boundary"
    observation_ids = _unique(
        (
            velocity.observation.observation_id,
            movement_onset.source_observation_id,
            takeoff.source_observation_id,
        )
    )
    system_refusal = _validate_phase_system(
        phase_system, claim=claim, observation_ids=observation_ids
    )
    if system_refusal is not None:
        return system_refusal
    input_refusal = _validate_phase_inputs(velocity, movement_onset, takeoff, claim=claim)
    if input_refusal is not None:
        return input_refusal
    if peak_negative_velocity is None:
        peak = detect_peak_negative_supported_system_com_velocity(
            velocity, movement_onset, takeoff, phase_system=phase_system
        )
        if isinstance(peak, RefusalResult):
            return peak
        peak_negative_velocity = peak
    if (
        not isinstance(peak_negative_velocity, CMJPhaseBoundary)
        or peak_negative_velocity.kind
        is not CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY
        or peak_negative_velocity.source_velocity_series_id != velocity.series.series_id
        or peak_negative_velocity.source_observation_id != movement_onset.source_observation_id
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("the peak-negative landmark from this exact velocity/source",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    selected_index: int | None = None
    for index in range(peak_negative_velocity.sample_index + 1, takeoff.sample_index + 1):
        if _velocity_sample(velocity, index) > 0.0:
            selected_index = index
            break
    if selected_index is None:
        return _phase_refusal(
            claim,
            (
                RefusalReasonCode.DIRECTION_CHANGE_UNRESOLVED,
                RefusalReasonCode.PROPULSION_ONSET_UNRESOLVED,
            ),
            ("a source sample strictly greater than 0.0 m/s after peak negative velocity",),
            observation_ids=observation_ids,
        )
    return _make_boundary(
        velocity,
        movement_onset,
        takeoff,
        kind=CMJPhaseBoundaryKind.DIRECTION_CHANGE,
        method=CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD,
        search_start_index=peak_negative_velocity.sample_index + 1,
        search_end_index=takeoff.sample_index,
        sample_index=selected_index,
        tie_policy="first qualifying source sample",
        velocity_threshold_policy="none; strict velocity > 0.0 m/s",
        interpolation_policy="none; discrete transition gap retained",
        evidence_decision=RES39_DECISION_PHASE_BOUNDARIES,
    )


def detect_cmj_propulsion_onset(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    direction_change: CMJPhaseBoundary | None = None,
    *,
    phase_system: RegistryReference = CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
) -> CMJPhaseBoundary | RefusalResult:
    """Expose the V1 local propulsion-onset view of the direction boundary."""

    claim = "detect RES-39 propulsion onset"
    observation_ids = _unique(
        (
            velocity.observation.observation_id,
            movement_onset.source_observation_id,
            takeoff.source_observation_id,
        )
    )
    system_refusal = _validate_phase_system(
        phase_system, claim=claim, observation_ids=observation_ids
    )
    if system_refusal is not None:
        return system_refusal
    input_refusal = _validate_phase_inputs(velocity, movement_onset, takeoff, claim=claim)
    if input_refusal is not None:
        return input_refusal
    if direction_change is None:
        detected = detect_cmj_direction_change_boundary(
            velocity, movement_onset, takeoff, phase_system=phase_system
        )
        if isinstance(detected, RefusalResult):
            return detected
        direction_change = detected
    if isinstance(direction_change, RefusalResult):
        return direction_change
    if not isinstance(direction_change, CMJPhaseBoundary):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PROPULSION_ONSET_UNRESOLVED,),
            ("registered direction-change boundary",),
            observation_ids=observation_ids,
        )
    if (
        direction_change.phase_system.stable_id != phase_system.stable_id
        or direction_change.kind is not CMJPhaseBoundaryKind.DIRECTION_CHANGE
        or direction_change.method.stable_id
        != CMJ_FIRST_STRICTLY_POSITIVE_SUPPORTED_SYSTEM_COM_VELOCITY_BOUNDARY_METHOD.stable_id
        or direction_change.source_observation_id != movement_onset.source_observation_id
        or direction_change.source_velocity_observation_id != velocity.observation.observation_id
        or direction_change.source_velocity_series_id != velocity.series.series_id
        or direction_change.source_timebase != velocity.series.timebase
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("the direction-change boundary from this exact velocity/source",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return _make_boundary(
        velocity,
        movement_onset,
        takeoff,
        kind=CMJPhaseBoundaryKind.PROPULSION_ONSET,
        method=direction_change.method,
        search_start_index=direction_change.search_start_index,
        search_end_index=direction_change.search_end_index,
        sample_index=direction_change.sample_index,
        tie_policy=direction_change.tie_policy,
        velocity_threshold_policy=direction_change.velocity_threshold_policy,
        interpolation_policy=direction_change.interpolation_policy,
        evidence_decision=RES39_DECISION_PHASE_BOUNDARIES,
    )


def _phase_occurrence_provenance(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    occurrence_id: InstanceIdentifier,
    phase_definition: CMJPhaseDefinition,
    start_boundary: CMJPhaseBoundary,
    end_boundary: CMJPhaseBoundary,
) -> Provenance:
    base = _merge_provenance(start_boundary.provenance, end_boundary.provenance)
    source_observation_ids = _phase_source_observation_ids(velocity, movement_onset, takeoff)
    source_acquisition_ids = tuple(
        sorted((item.acquisition_id for item in base.acquisitions), key=lambda item: item.qualified)
    )
    parameters = (
        MetadataEntry("phase_system", CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.stable_id),
        MetadataEntry("phase_definition", phase_definition.reference.stable_id),
        MetadataEntry("source_observation_id", movement_onset.source_observation_id.qualified),
        MetadataEntry("source_signal_id", movement_onset.source_signal_id.qualified),
        MetadataEntry(
            "source_velocity_observation_id", velocity.observation.observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", velocity.series.series_id.qualified),
        MetadataEntry("start_boundary_id", start_boundary.boundary_id.qualified),
        MetadataEntry("end_boundary_id", end_boundary.boundary_id.qualified),
        MetadataEntry("boundary_convention", CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION.stable_id),
        MetadataEntry(
            "sample_support",
            canonical_json(
                CMJPhaseSampleSupport(start_boundary.sample_index, end_boundary.sample_index)
            ),
        ),
        MetadataEntry("interpolation_policy", "none; exact source samples only"),
        MetadataEntry("velocity_threshold_policy", "none; strict positive rule is > 0.0 m/s"),
        MetadataEntry(
            "source_velocity_initial_condition", canonical_json(velocity.initial_velocity_condition)
        ),
        MetadataEntry(
            "source_velocity_integration_interval",
            canonical_json(velocity.series.integration_interval),
        ),
        MetadataEntry(
            "source_velocity_source_signal_ids",
            canonical_json(velocity.series.source_signal_ids),
        ),
        MetadataEntry(
            "source_velocity_source_observation_ids",
            canonical_json(velocity.series.source_observation_ids),
        ),
        MetadataEntry(
            "source_velocity_source_measurement_identity_ids",
            canonical_json(velocity.series.source_measurement_identity_ids),
        ),
        MetadataEntry(
            "source_velocity_version", canonical_json(velocity.observation.identity.version)
        ),
        MetadataEntry("source_system_contract", canonical_json(velocity.system_contract)),
    )
    digest = canonical_hash(
        {
            "phase_system": CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
            "phase_definition": phase_definition.reference,
            "source_velocity_observation": velocity.observation.observation_id,
            "start_boundary": start_boundary.boundary_id,
            "end_boundary": end_boundary.boundary_id,
            "parameters": parameters,
        }
    ).removeprefix("sha256:")[:24]
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-phase:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
        parameters=parameters,
        software_version=RES39_SOFTWARE_VERSION,
        output_entity_id=occurrence_id,
    )
    evidence = EvidenceReference(
        RES39_DECISION_PHASE_SYSTEM, "registered RES-39 phase-system decision"
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=occurrence_id,
        source_observation_ids=source_observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        supported_by=(RES39_DECISION_PHASE_SYSTEM, RES39_DECISION_PHASE_BOUNDARIES),
        evidence_references=(evidence,),
        recorded_at=base.recorded_at,
    )
    return _add_entity_edges(
        provenance,
        processing_run_id=run.processing_run_id,
        entity_ids=_unique(
            (
                velocity.observation.observation_id,
                velocity.series.series_id,
                movement_onset.occurrence_id,
                takeoff.occurrence_id,
                start_boundary.boundary_id,
                end_boundary.boundary_id,
            )
        ),
    )


def _make_phase_occurrence(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    phase_definition: CMJPhaseDefinition,
    start_boundary: CMJPhaseBoundary,
    end_boundary: CMJPhaseBoundary,
) -> CMJPhaseOccurrence:
    occurrence_digest = canonical_hash(
        {
            "phase_system": CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
            "phase_definition": phase_definition.reference,
            "source_observation": movement_onset.source_observation_id,
            "source_velocity_observation": velocity.observation.observation_id,
            "start_boundary": start_boundary.boundary_id,
            "end_boundary": end_boundary.boundary_id,
        }
    ).removeprefix("sha256:")[:24]
    occurrence_id = InstanceIdentifier(
        "phase-occurrence", f"cmj-{phase_definition.label.value.casefold()}:{occurrence_digest}"
    )
    velocity_identity = velocity.observation.identity
    if not isinstance(velocity_identity, CMJMeasurementIdentity):
        raise ValueError("velocity observation must preserve a CMJ measurement identity")
    if velocity.series.integration_interval is None or velocity.series.integration_method is None:
        raise ValueError("velocity series must preserve its exact integration identity")
    source_event_ids = _unique(
        tuple(
            boundary.source_event_id
            for boundary in (start_boundary, end_boundary)
            if boundary.source_event_id is not None
        )
    )
    provenance = _phase_occurrence_provenance(
        velocity,
        movement_onset,
        takeoff,
        occurrence_id=occurrence_id,
        phase_definition=phase_definition,
        start_boundary=start_boundary,
        end_boundary=end_boundary,
    )
    return CMJPhaseOccurrence(
        occurrence_id=occurrence_id,
        phase_system=CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
        phase_definition=phase_definition.reference,
        source_context=velocity.observation.context,
        source_observation_id=movement_onset.source_observation_id,
        source_signal_id=movement_onset.source_signal_id,
        source_artifact_id=movement_onset.source_artifact_id,
        source_acquisition_id=movement_onset.source_acquisition_id,
        source_measurement_identity=movement_onset.source_measurement_identity,
        source_velocity_observation_id=velocity.observation.observation_id,
        source_velocity_series_id=velocity.series.series_id,
        source_velocity_measurement_identity=velocity_identity,
        source_velocity_operation=velocity.series.operation,
        source_velocity_integration_method=velocity.series.integration_method,
        source_velocity_integration_interval=velocity.series.integration_interval,
        source_velocity_initial_condition=velocity.initial_velocity_condition,
        source_velocity_version=velocity_identity.version,
        source_velocity_processing_parameters=velocity_identity.processing.method_parameters,
        source_velocity_filtering=velocity_identity.processing.filtering,
        source_velocity_source_signal_ids=velocity.series.source_signal_ids,
        source_velocity_source_observation_ids=velocity.series.source_observation_ids,
        source_velocity_source_measurement_identity_ids=velocity.series.source_measurement_identity_ids,
        source_system_contract=velocity.system_contract,
        start_boundary=start_boundary,
        end_boundary=end_boundary,
        start_time_s=start_boundary.boundary_time_s,
        end_time_s=end_boundary.boundary_time_s,
        sample_support=CMJPhaseSampleSupport(
            start_boundary.sample_index, end_boundary.sample_index
        ),
        boundary_convention=CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION,
        interpolation_policy="none; exact source samples only",
        velocity_threshold_policy="none; strict positive rule is > 0.0 m/s",
        source_event_ids=source_event_ids,
        evidence_decision=RES39_DECISION_PHASE_SYSTEM,
        provenance=provenance,
    )


def construct_cmj_phase_occurrences(
    velocity: SupportedSystemComVelocityResult,
    movement_onset: CMJEventOccurrence,
    takeoff: CMJEventOccurrence,
    *,
    phase_system: RegistryReference = CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
) -> tuple[CMJPhaseOccurrence, ...] | RefusalResult:
    """Construct the closed V1 unweighting, braking, and propulsion occurrences."""

    claim = "construct RES-39 CMJ phase occurrences"
    observation_ids = _unique(
        (
            velocity.observation.observation_id,
            movement_onset.source_observation_id,
            takeoff.source_observation_id,
        )
    )
    system_refusal = _validate_phase_system(
        phase_system, claim=claim, observation_ids=observation_ids
    )
    if system_refusal is not None:
        return system_refusal
    input_refusal = _validate_phase_inputs(velocity, movement_onset, takeoff, claim=claim)
    if input_refusal is not None:
        return input_refusal
    peak = detect_peak_negative_supported_system_com_velocity(
        velocity, movement_onset, takeoff, phase_system=phase_system
    )
    if isinstance(peak, RefusalResult):
        return peak
    direction = detect_cmj_direction_change_boundary(
        velocity, movement_onset, takeoff, peak, phase_system=phase_system
    )
    if isinstance(direction, RefusalResult):
        return direction
    propulsion_onset = detect_cmj_propulsion_onset(
        velocity,
        movement_onset,
        takeoff,
        direction,
        phase_system=phase_system,
    )
    if isinstance(propulsion_onset, RefusalResult):
        return propulsion_onset
    if (
        peak.sample_index <= movement_onset.sample_index
        or direction.sample_index <= peak.sample_index
        or propulsion_onset.sample_index >= takeoff.sample_index
        or peak.boundary_time_s <= movement_onset.event_time_s
        or direction.boundary_time_s <= peak.boundary_time_s
        or propulsion_onset.boundary_time_s >= takeoff.event_time_s
    ):
        return _phase_refusal(
            claim,
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("each registered V1 phase must contain at least one source interval",),
            observation_ids=observation_ids,
        )
    unweighting = _make_phase_occurrence(
        velocity,
        movement_onset,
        takeoff,
        phase_definition=CMJ_UNWEIGHTING_PHASE_V1,
        start_boundary=_make_boundary(
            velocity,
            movement_onset,
            takeoff,
            kind=CMJPhaseBoundaryKind.MOVEMENT_ONSET,
            method=movement_onset.detector_method.reference,
            search_start_index=movement_onset.sample_index,
            search_end_index=movement_onset.sample_index,
            sample_index=movement_onset.sample_index,
            tie_policy="sealed RES-36 event sample",
            velocity_threshold_policy="not a phase velocity threshold; sealed force event",
            interpolation_policy="none; sealed RES-36 sample-attached event",
            evidence_decision=RES36_DECISION_EVENT_SEMANTICS,
            source_event=movement_onset,
        ),
        end_boundary=peak,
    )
    braking = _make_phase_occurrence(
        velocity,
        movement_onset,
        takeoff,
        phase_definition=CMJ_BRAKING_PHASE_V1,
        start_boundary=peak,
        end_boundary=direction,
    )
    propulsion = _make_phase_occurrence(
        velocity,
        movement_onset,
        takeoff,
        phase_definition=CMJ_PROPULSION_PHASE_V1,
        start_boundary=propulsion_onset,
        end_boundary=_make_boundary(
            velocity,
            movement_onset,
            takeoff,
            kind=CMJPhaseBoundaryKind.TAKEOFF,
            method=takeoff.detector_method.reference,
            search_start_index=takeoff.sample_index,
            search_end_index=takeoff.sample_index,
            sample_index=takeoff.sample_index,
            tie_policy="sealed RES-36 event sample",
            velocity_threshold_policy="not a phase velocity threshold; sealed force event",
            interpolation_policy="none; sealed RES-36 sample-attached event",
            evidence_decision=RES36_DECISION_EVENT_SEMANTICS,
            source_event=takeoff,
        ),
    )
    return (unweighting, braking, propulsion)


derive_cmj_phase_occurrences = construct_cmj_phase_occurrences


def _phase_metric_spec(
    metric: CMJPhaseMetric,
) -> tuple[CMJPhaseLabel, RegistryReference, RegistryReference, RegistryReference, UnitReference]:
    if metric is CMJPhaseMetric.UNWEIGHTING_DURATION:
        return (
            CMJPhaseLabel.UNWEIGHTING,
            CMJ_UNWEIGHTING_DURATION_MEASURAND,
            CMJ_UNWEIGHTING_DURATION_METRIC,
            CMJ_PHASE_DURATION_OPERATION,
            SECOND,
        )
    if metric is CMJPhaseMetric.BRAKING_DURATION:
        return (
            CMJPhaseLabel.BRAKING,
            CMJ_BRAKING_DURATION_MEASURAND,
            CMJ_BRAKING_DURATION_METRIC,
            CMJ_PHASE_DURATION_OPERATION,
            SECOND,
        )
    if metric is CMJPhaseMetric.PROPULSION_DURATION:
        return (
            CMJPhaseLabel.PROPULSION,
            CMJ_PROPULSION_DURATION_MEASURAND,
            CMJ_PROPULSION_DURATION_METRIC,
            CMJ_PHASE_DURATION_OPERATION,
            SECOND,
        )
    if metric is CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE:
        return (
            CMJPhaseLabel.BRAKING,
            CMJ_BRAKING_NET_VERTICAL_IMPULSE_MEASURAND,
            CMJ_BRAKING_NET_VERTICAL_IMPULSE_METRIC,
            CMJ_PHASE_NET_VERTICAL_IMPULSE_OPERATION,
            NEWTON_SECOND,
        )
    if metric is CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE:
        return (
            CMJPhaseLabel.PROPULSION,
            CMJ_PROPULSION_NET_VERTICAL_IMPULSE_MEASURAND,
            CMJ_PROPULSION_NET_VERTICAL_IMPULSE_METRIC,
            CMJ_PHASE_NET_VERTICAL_IMPULSE_OPERATION,
            NEWTON_SECOND,
        )
    if metric is CMJPhaseMetric.BRAKING_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE:
        return (
            CMJPhaseLabel.BRAKING,
            CMJ_BRAKING_DISPLACEMENT_CHANGE_MEASURAND,
            CMJ_BRAKING_DISPLACEMENT_CHANGE_METRIC,
            CMJ_PHASE_RELATIVE_DISPLACEMENT_CHANGE_OPERATION,
            METER,
        )
    return (
        CMJPhaseLabel.PROPULSION,
        CMJ_PROPULSION_DISPLACEMENT_CHANGE_MEASURAND,
        CMJ_PROPULSION_DISPLACEMENT_CHANGE_METRIC,
        CMJ_PHASE_RELATIVE_DISPLACEMENT_CHANGE_OPERATION,
        METER,
    )


def _metric_refusal(
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing: tuple[str, ...],
    phase: CMJPhaseOccurrence | None = None,
) -> RefusalResult:
    return _phase_refusal(
        blocked_claim,
        reason_codes,
        missing,
        observation_ids=(phase.source_velocity_observation_id,) if phase is not None else (),
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED
        if RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED in reason_codes
        else RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
    )


def _validate_metric_phase(
    phase: CMJPhaseOccurrence,
    metric: CMJPhaseMetric,
) -> RefusalResult | None:
    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("complete CMJPhaseOccurrence",),
        )
    expected_phase, _, _, _, _ = _phase_metric_spec(metric)
    if phase.label is not expected_phase:
        return _metric_refusal(
            f"calculate {metric.value}",
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            (f"phase occurrence labeled {expected_phase.value}",),
            phase,
        )
    return None


def _validate_mechanics_source(
    phase: CMJPhaseOccurrence,
    source_observation: ScientificMeasurementObservation,
    source_series_id: InstanceIdentifier,
    source_series_quantity: CMJMechanicsQuantity,
    source_timebase: SignalTimebase,
    source_system_contract: CMJMechanicalSystemContract,
    source_result: NetVerticalForceResult | SupportedSystemComRelativeDisplacementResult,
) -> RefusalResult | None:
    observation_ids = _unique(
        (
            phase.source_velocity_observation_id,
            source_observation.observation_id,
            *(
                (source_result.source_system_weight_observation_id,)
                if isinstance(source_result, NetVerticalForceResult)
                else ()
            ),
        )
    )
    if source_system_contract != phase.source_system_contract:
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("mechanics result with the exact phase supported-system contract",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if source_timebase != phase.start_boundary.source_timebase:
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,),
            ("mechanics result with the exact phase timebase",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if source_series_id.instance_type != "signal":
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("registered mechanics series identifier",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if source_series_quantity not in {
        CMJMechanicsQuantity.NET_VERTICAL_FORCE,
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
    }:
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("registered net-force or supported-system displacement source",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if source_result.observation is not source_observation or source_result.series.series_id != (
        source_series_id
    ):
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("the exact typed mechanics result named by the phase metric source fields",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if source_result.series.quantity is not source_series_quantity:
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("mechanics result quantity matching its preserved source series",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not _provenance_has_entity(source_observation.provenance, phase.source_observation_id):
        return _phase_refusal(
            "calculate RES-39 phase metric",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("mechanics provenance linked to the phase source observation",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if isinstance(source_result, NetVerticalForceResult):
        reference = phase.source_velocity_initial_condition
        parameters = {
            entry.key: entry.value
            for entry in source_observation.identity.processing.method_parameters
        }
        if (
            source_result.source_system_weight_observation_id
            != reference.source_system_weight_observation_id
            or source_result.source_system_weight_observation_id
            not in phase.source_velocity_source_observation_ids
            or source_series_id not in phase.source_velocity_source_signal_ids
            or parameters.get("system_weight_segment") != canonical_json(reference.weighing_segment)
            or parameters.get("system_weight_qc") != canonical_json(reference.weighing_qc)
        ):
            return _phase_refusal(
                "calculate RES-39 phase metric",
                (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
                ("the exact RES-37 net-force/system-weight lineage used by the phase velocity",),
                observation_ids=observation_ids,
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
    else:
        parameters = {
            entry.key: entry.value
            for entry in source_observation.identity.processing.method_parameters
        }
        origin = source_result.displacement_origin
        if (
            source_result.series.initial_velocity_condition
            != phase.source_velocity_initial_condition
            or source_result.series.integration_interval
            != phase.source_velocity_integration_interval
            or origin.source_velocity_series_id != phase.source_velocity_series_id
            or parameters.get("source_velocity_observation_id")
            != phase.source_velocity_observation_id.qualified
            or parameters.get("source_velocity_series_id")
            != phase.source_velocity_series_id.qualified
        ):
            return _phase_refusal(
                "calculate RES-39 phase metric",
                (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
                ("the exact RES-37 displacement lineage from the phase velocity and origin",),
                observation_ids=observation_ids,
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
    return None


def _metric_parameters(
    phase: CMJPhaseOccurrence,
    metric: CMJPhaseMetric,
    *,
    operation: RegistryReference,
    source_observation_id: InstanceIdentifier,
    source_series_id: InstanceIdentifier,
    source_quantity: CMJMechanicsQuantity,
    source_operation: RegistryReference,
    source_timebase: SignalTimebase,
    source_system_contract: CMJMechanicalSystemContract,
    interval: CMJIntegrationInterval | None,
    equation: str,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("metric", metric.value),
        MetadataEntry("metric_definition", _phase_metric_spec(metric)[2].stable_id),
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("phase_system", phase.phase_system.stable_id),
        MetadataEntry("phase_definition", phase.phase_definition.stable_id),
        MetadataEntry("phase_occurrence_id", phase.occurrence_id.qualified),
        MetadataEntry("start_boundary_id", phase.start_boundary.boundary_id.qualified),
        MetadataEntry("end_boundary_id", phase.end_boundary.boundary_id.qualified),
        MetadataEntry("start_time_s", phase.start_time_s),
        MetadataEntry("end_time_s", phase.end_time_s),
        MetadataEntry("sample_support", canonical_json(phase.sample_support)),
        MetadataEntry("boundary_convention", phase.boundary_convention.stable_id),
        MetadataEntry("interpolation_policy", phase.interpolation_policy),
        MetadataEntry("velocity_threshold_policy", phase.velocity_threshold_policy),
        MetadataEntry("equation", equation),
        MetadataEntry("source_mechanics_observation_id", source_observation_id.qualified),
        MetadataEntry("source_mechanics_series_id", source_series_id.qualified),
        MetadataEntry("source_mechanics_quantity", source_quantity.value),
        MetadataEntry("source_mechanics_operation", source_operation.stable_id),
        MetadataEntry("source_timebase", canonical_json(source_timebase)),
        MetadataEntry("source_system_contract", canonical_json(source_system_contract)),
        MetadataEntry(
            "source_velocity_observation_id", phase.source_velocity_observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", phase.source_velocity_series_id.qualified),
        MetadataEntry("source_velocity_operation", phase.source_velocity_operation.stable_id),
        MetadataEntry(
            "source_velocity_integration_method", phase.source_velocity_integration_method.stable_id
        ),
        MetadataEntry(
            "source_velocity_initial_condition",
            canonical_json(phase.source_velocity_initial_condition),
        ),
        MetadataEntry(
            "source_velocity_processing_parameters",
            canonical_json(phase.source_velocity_processing_parameters),
        ),
        MetadataEntry("filtering", canonical_json(phase.source_velocity_filtering)),
        MetadataEntry("drift_correction", "none"),
        MetadataEntry("phase_inclusion_semantics", phase.sample_support.interval_semantics),
        MetadataEntry(
            "integration_interval", canonical_json(interval) if interval is not None else None
        ),
        MetadataEntry(
            "claim_ceiling",
            "method-specific supported-system mechanical quantity; no athlete-only relabeling",
        ),
    )


def _build_metric(
    phase: CMJPhaseOccurrence,
    metric: CMJPhaseMetric,
    value: float,
    *,
    source_context: ObservationContext,
    source_identity: CMJMeasurementIdentity,
    base_provenance: Provenance,
    source_observation_id: InstanceIdentifier,
    source_series_id: InstanceIdentifier,
    source_quantity: CMJMechanicsQuantity,
    source_operation: RegistryReference,
    source_timebase: SignalTimebase,
    source_system_contract: CMJMechanicalSystemContract,
    interval: CMJIntegrationInterval | None,
    equation: str,
) -> CMJPhaseMetricResult:
    _, measurand, metric_ref, operation, unit_object = _phase_metric_spec(metric)
    unit = unit_object
    _finite(value, "phase metric value")
    parameters = _metric_parameters(
        phase,
        metric,
        operation=operation,
        source_observation_id=source_observation_id,
        source_series_id=source_series_id,
        source_quantity=source_quantity,
        source_operation=source_operation,
        source_timebase=source_timebase,
        source_system_contract=source_system_contract,
        interval=interval,
        equation=equation,
    )
    digest = canonical_hash(
        {
            "metric": metric,
            "phase_occurrence": phase.occurrence_id,
            "source_observation": source_observation_id,
            "source_series": source_series_id,
            "value": value,
            "parameters": parameters,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = InstanceIdentifier(
        "observation", f"cmj-phase-metric:{metric.value.casefold()}:{digest}"
    )
    base_observation_ids = _unique(
        (
            phase.source_observation_id,
            phase.source_velocity_observation_id,
            source_observation_id,
        )
    )
    source_artifact_ids = tuple(
        sorted(
            (item.artifact_id for item in base_provenance.source_artifacts),
            key=lambda item: item.qualified,
        )
    )
    source_acquisition_ids = tuple(
        sorted(
            (item.acquisition_id for item in base_provenance.acquisitions),
            key=lambda item: item.qualified,
        )
    )
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-phase-metric:{digest}"),
        source_artifact_ids=source_artifact_ids,
        method=operation,
        parameters=parameters,
        software_version=RES39_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    supported_by = (
        RES39_DECISION_PHASE_METRICS,
        RES39_DECISION_PHASE_SYSTEM,
        RES39_DECISION_PHASE_BOUNDARIES,
        CMJ_MECHANICS_SYSTEM_CONTRACT,
        *(
            (RES37_DECISION_IMPULSE_INTEGRATION,)
            if interval is not None
            else (RES37_DECISION_DISPLACEMENT_REFERENCE,)
            if source_quantity
            is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT
            else ()
        ),
    )
    provenance = _provenance_with_run(
        base_provenance,
        processing_run=processing_run,
        output_entity_id=observation_id,
        source_observation_ids=base_observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        supported_by=supported_by,
        evidence_references=(
            EvidenceReference(RES39_DECISION_PHASE_METRICS, "registered V1 phase metric"),
        ),
        recorded_at=source_context.observed_at,
    )
    provenance = _add_entity_edges(
        provenance,
        processing_run_id=processing_run.processing_run_id,
        entity_ids=_unique((phase.occurrence_id, source_series_id)),
    )
    sign = source_identity.acquisition.sign_convention
    identity = _derived_identity(
        source_identity,
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"cmj-phase-metric-{metric.value.casefold()}-{digest}",
            CMJ_REGISTRY_VERSION,
        ),
        measurand=measurand,
        metric=metric_ref,
        processing=ProcessingIdentity(
            phase_definitions=(phase.phase_definition,),
            registered_operation=operation,
            method_parameters=parameters,
            integration_method=CMJ_TRAPEZOIDAL_INTEGRATION_METHOD if interval is not None else None,
            unit=unit,
            sign_convention=sign,
        ),
        processing_method=operation,
        software_version=RES39_SOFTWARE_VERSION,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=source_context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier(
                "result", f"cmj-phase-metric:{metric.value.casefold()}:{digest}"
            ),
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(ValueOrigin.DERIVED_MECHANICAL_QUANTITY, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=_UNCERTAINTY_NOTE,
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return CMJPhaseMetricResult(
        observation=observation,
        metric=metric,
        phase_occurrence=phase,
        source_mechanics_observation_id=source_observation_id,
        source_mechanics_series_id=source_series_id,
        source_mechanics_quantity=source_quantity,
        source_mechanics_operation=source_operation,
        source_timebase=source_timebase,
        source_system_contract=source_system_contract,
        source_integration_interval=interval,
    )


def calculate_cmj_phase_duration(
    phase: CMJPhaseOccurrence,
) -> CMJPhaseMetricResult | RefusalResult:
    """Calculate duration directly from the registered phase boundary times."""

    metric_by_label = {
        CMJPhaseLabel.UNWEIGHTING: CMJPhaseMetric.UNWEIGHTING_DURATION,
        CMJPhaseLabel.BRAKING: CMJPhaseMetric.BRAKING_DURATION,
        CMJPhaseLabel.PROPULSION: CMJPhaseMetric.PROPULSION_DURATION,
    }
    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "calculate RES-39 phase duration",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("complete CMJPhaseOccurrence",),
        )
    metric = metric_by_label[phase.label]
    phase_refusal = _validate_metric_phase(phase, metric)
    if phase_refusal is not None:
        return phase_refusal
    return _build_metric(
        phase,
        metric,
        phase.end_time_s - phase.start_time_s,
        source_context=phase.source_context,
        source_identity=phase.source_velocity_measurement_identity,
        base_provenance=phase.provenance,
        source_observation_id=phase.source_velocity_observation_id,
        source_series_id=phase.source_velocity_series_id,
        source_quantity=CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
        source_operation=phase.source_velocity_operation,
        source_timebase=phase.start_boundary.source_timebase,
        source_system_contract=phase.source_system_contract,
        interval=None,
        equation="duration_phase = end_time_s - start_time_s",
    )


def _phase_impulse_metric(phase: CMJPhaseOccurrence) -> CMJPhaseMetric:
    return {
        CMJPhaseLabel.BRAKING: CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE,
        CMJPhaseLabel.PROPULSION: CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
    }[phase.label]


def calculate_cmj_phase_net_vertical_impulse(
    phase: CMJPhaseOccurrence,
    net_force: NetVerticalForceResult,
) -> CMJPhaseMetricResult | RefusalResult:
    """Reuse RES-37 trapezoidal net-force integration over one V1 phase."""

    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("complete CMJPhaseOccurrence",),
        )
    if phase.label not in {CMJPhaseLabel.BRAKING, CMJPhaseLabel.PROPULSION}:
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            ("registered braking or propulsion phase",),
            phase,
        )
    metric = _phase_impulse_metric(phase)
    phase_refusal = _validate_metric_phase(phase, metric)
    if phase_refusal is not None:
        return phase_refusal
    if not isinstance(net_force, NetVerticalForceResult):
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("exact RES-37 NetVerticalForceResult",),
            phase,
        )
    source_refusal = _validate_mechanics_source(
        phase,
        net_force.observation,
        net_force.series.series_id,
        net_force.series.quantity,
        net_force.series.timebase,
        net_force.system_contract,
        net_force,
    )
    if source_refusal is not None:
        return source_refusal
    start = phase.start_boundary.sample_index
    end = phase.end_boundary.sample_index
    if (
        start < net_force.series.sample_start_index
        or end >= net_force.series.sample_start_index + len(net_force.series.samples)
        or end <= start
    ):
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("phase endpoints inside net-force series with at least one interval",),
            phase,
        )
    interval = CMJIntegrationInterval.explicit_sample(net_force.series.series_id, start, end)
    integrated = integrate_net_vertical_impulse(net_force, interval)
    if isinstance(integrated, RefusalResult):
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("RES-37 registered trapezoidal integration over the phase interval",),
            phase,
        )
    net_force_identity = net_force.observation.identity
    if not isinstance(net_force_identity, CMJMeasurementIdentity):
        return _metric_refusal(
            "calculate RES-39 phase net vertical impulse",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJ measurement identity on the exact net-force result",),
            phase,
        )
    return _build_metric(
        phase,
        metric,
        integrated.value_ns,
        source_context=net_force.observation.context,
        source_identity=net_force_identity,
        base_provenance=_merge_provenance(phase.provenance, net_force.observation.provenance),
        source_observation_id=net_force.observation.observation_id,
        source_series_id=net_force.series.series_id,
        source_quantity=net_force.series.quantity,
        source_operation=net_force.series.operation,
        source_timebase=net_force.series.timebase,
        source_system_contract=net_force.system_contract,
        interval=interval,
        equation=(
            "phase_net_vertical_impulse = RES-37 trapezoidal integral of F_net "
            "over (start_index, end_index]"
        ),
    )


def _phase_displacement_metric(phase: CMJPhaseOccurrence) -> CMJPhaseMetric:
    return {
        CMJPhaseLabel.BRAKING: (
            CMJPhaseMetric.BRAKING_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE
        ),
        CMJPhaseLabel.PROPULSION: (
            CMJPhaseMetric.PROPULSION_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_CHANGE
        ),
    }[phase.label]


def calculate_cmj_phase_relative_displacement_change(
    phase: CMJPhaseOccurrence,
    displacement: SupportedSystemComRelativeDisplacementResult,
) -> CMJPhaseMetricResult | RefusalResult:
    """Calculate z(end)-z(start) from the sealed relative displacement series."""

    if not isinstance(phase, CMJPhaseOccurrence):
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("complete CMJPhaseOccurrence",),
        )
    if phase.label not in {CMJPhaseLabel.BRAKING, CMJPhaseLabel.PROPULSION}:
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED,),
            ("registered braking or propulsion phase",),
            phase,
        )
    metric = _phase_displacement_metric(phase)
    phase_refusal = _validate_metric_phase(phase, metric)
    if phase_refusal is not None:
        return phase_refusal
    if not isinstance(displacement, SupportedSystemComRelativeDisplacementResult):
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("exact RES-37 supported-system relative displacement result",),
            phase,
        )
    source_refusal = _validate_mechanics_source(
        phase,
        displacement.observation,
        displacement.series.series_id,
        displacement.series.quantity,
        displacement.series.timebase,
        displacement.system_contract,
        displacement,
    )
    if source_refusal is not None:
        return source_refusal
    start = phase.start_boundary.sample_index
    end = phase.end_boundary.sample_index
    first = displacement.series.sample_start_index
    last = first + len(displacement.series.samples) - 1
    if start < first or end > last or end <= start:
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_INTERVAL_INVALID,),
            ("displacement series support for both sample-attached phase endpoints",),
            phase,
        )
    if phase.interpolation_policy != "none; exact source samples only":
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_BOUNDARY_UNRESOLVED,),
            ("registered displacement interpolation authority for sub-sample boundaries",),
            phase,
        )
    value = displacement.series.samples[end - first] - displacement.series.samples[start - first]
    displacement_identity = displacement.observation.identity
    if not isinstance(displacement_identity, CMJMeasurementIdentity):
        return _metric_refusal(
            "calculate RES-39 phase relative displacement change",
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("CMJ measurement identity on the exact displacement result",),
            phase,
        )
    return _build_metric(
        phase,
        metric,
        value,
        source_context=displacement.observation.context,
        source_identity=displacement_identity,
        base_provenance=_merge_provenance(phase.provenance, displacement.observation.provenance),
        source_observation_id=displacement.observation.observation_id,
        source_series_id=displacement.series.series_id,
        source_quantity=displacement.series.quantity,
        source_operation=displacement.series.operation,
        source_timebase=displacement.series.timebase,
        source_system_contract=displacement.system_contract,
        interval=None,
        equation="delta_z_phase = z(end_index) - z(start_index)",
    )


calculate_cmj_phase_supported_system_com_relative_displacement_change = (
    calculate_cmj_phase_relative_displacement_change
)


def _source_measurement_method_key(identity: CMJMeasurementIdentity) -> tuple[object, ...]:
    acquisition = identity.acquisition
    processing = identity.processing
    return (
        identity.semantic.protocol_identity,
        identity.semantic.construct.stable_id,
        identity.semantic.test_family.stable_id,
        identity.semantic.measurand.stable_id,
        identity.semantic.metric_definition.stable_id,
        acquisition.device,
        acquisition.measuring_system,
        acquisition.hardware_firmware,
        acquisition.sensor_channel,
        acquisition.sampling,
        acquisition.calibration_reference,
        acquisition.physical_axis,
        acquisition.reference_frame,
        acquisition.unit,
        acquisition.sign_convention,
        _timebase_method_key(acquisition.timebase),
        acquisition.acquisition_software_version,
        acquisition.calibration,
        acquisition.zeroing,
        acquisition.processing_state,
        acquisition.arrangement,
        acquisition.channel,
        acquisition.available_channels,
        acquisition.combination_lineage,
        processing.registered_operation,
        processing.estimator,
        processing.filtering,
        processing.differentiation_method,
        processing.integration_method,
        processing.unit,
        processing.sign_convention,
        processing.normalization,
        processing.trial_selection,
        processing.aggregation,
        identity.version.processing_method,
        identity.version.method_registry_version,
        identity.version.software_version,
        identity.version.hardware_firmware,
    )


_INSTANCE_METADATA_KEYS = frozenset(
    {
        "source_id",
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
        "search_start_index",
        "search_end_index",
        "start_index",
        "end_index",
        "event_time_s",
        "time_s",
        "timestamp",
    }
)
_INSTANCE_METADATA_SUFFIXES = (
    "_observation_id",
    "_signal_id",
    "_artifact_id",
    "_acquisition_id",
    "_identity_id",
    "_event_id",
    "_event_ids",
    "_occurrence_id",
    "_sample_index",
    "_start_index",
    "_end_index",
    "_time_s",
    "_timestamp",
)


def _method_metadata_key(
    parameters: tuple[MetadataEntry, ...],
) -> tuple[tuple[str, object], ...]:
    """Retain method metadata while excluding embedded instance coordinates."""

    return tuple(
        (entry.key, entry.value)
        for entry in parameters
        if entry.key not in _INSTANCE_METADATA_KEYS
        and not entry.key.endswith(_INSTANCE_METADATA_SUFFIXES)
    )


def _processing_method_policy_key(
    parameters: tuple[MetadataEntry, ...],
) -> tuple[tuple[str, object], ...]:
    policy_names = {
        "filtering",
        "interpolation",
        "resampling",
        "drift_correction",
        "endpoint_constraint",
        "uncertainty_propagation",
        "integration_boundary",
        "integration_method",
    }
    return tuple((entry.key, entry.value) for entry in parameters if entry.key in policy_names)


def _timebase_method_key(
    timebase: SignalTimebase | TimebaseIdentity | None,
) -> tuple[object, ...] | None:
    """Describe timing method characteristics without trial clock coordinates."""

    if timebase is None:
        return None
    if isinstance(timebase, RegularTimebase):
        return ("REGULAR", timebase.sample_rate_hz)
    if isinstance(timebase, ExplicitTimebase):
        return ("EXPLICIT",)
    if isinstance(timebase, TimebaseIdentity):
        return (
            timebase.kind.value,
            timebase.sample_rate_hz,
            timebase.clock_reference.stable_id if timebase.clock_reference else None,
            timebase.description,
        )
    return ("UNKNOWN", type(timebase).__name__)


def _event_detector_parameter_method_key(
    parameters: CMJEventDetectorParameters,
) -> tuple[tuple[str, object], ...]:
    """Retain detector configuration while excluding baseline realization data."""

    baseline_segment = parameters.baseline_segment
    return (
        ("threshold_n", parameters.threshold_n),
        (
            "baseline_selection_method",
            baseline_segment.selection_method.stable_id if baseline_segment else None,
        ),
        (
            "baseline_selection_parameters",
            _method_metadata_key(baseline_segment.selection_parameters)
            if baseline_segment
            else None,
        ),
        ("sigma_multiplier", parameters.sigma_multiplier),
        ("direction", parameters.direction.value if parameters.direction else None),
        ("dwell_samples", parameters.dwell_samples),
        ("search_start_index", parameters.search_start_index),
    )


def _phase_event_method_key(event: CMJEventOccurrence | None) -> object:
    if event is None:
        return None
    return (
        event.definition.reference.stable_id,
        event.detector_method.reference.stable_id,
        event.detector_method.threshold_family.value,
        _event_detector_parameter_method_key(event.detector_parameters),
        _timebase_method_key(event.source_timebase),
    )


def _velocity_integration_method_key(
    interval: CMJIntegrationInterval | None,
) -> tuple[object, ...] | None:
    """Describe integration semantics without realized interval coordinates."""

    if interval is None:
        return None
    return (
        interval.kind,
        interval.boundary_convention.stable_id,
        interval.integration_method.stable_id,
        _phase_event_method_key(interval.start_event),
        _phase_event_method_key(interval.end_event),
    )


def _zero_velocity_reference_method_key(
    condition: QualifiedZeroVelocityReference | InitialVelocityCondition | None,
) -> object:
    """Retain zero-reference authority semantics without trial realization fields."""

    if condition is None:
        return None
    if isinstance(condition, QualifiedZeroVelocityReference):
        segment = condition.weighing_segment
        return (
            "QUALIFIED",
            condition.method.stable_id,
            condition.evidence_decision.stable_id,
            condition.unit.identifier.stable_id,
            segment.selection_method.stable_id,
            _method_metadata_key(segment.selection_parameters),
            condition.weighing_qc.acceptability_adjudicated,
        )
    return (
        "LEGACY",
        condition.method.stable_id,
        condition.unit.identifier.stable_id,
        condition.assumption,
        _phase_event_method_key(condition.reference_event),
    )


def _phase_velocity_processing_method_key(
    parameters: tuple[MetadataEntry, ...],
) -> tuple[tuple[str, object], ...]:
    """Retain upstream processing semantics while excluding trial realizations."""

    ignored_keys = {
        "source_signal_ids",
        "source_observation_ids",
        "source_measurement_identity_ids",
        "source_event_ids",
        "integration_interval",
        "zero_velocity_reference",
        "displacement_origin",
        "source_sample_count",
        "sample_start_index",
        "sample_end_index",
        "selected_sample_index",
        "search_start_index",
        "search_end_index",
    }
    ignored_suffixes = (
        "_observation_id",
        "_series_id",
        "_signal_id",
        "_artifact_id",
        "_acquisition_id",
        "_identity_id",
        "_event_id",
        "_event_ids",
        "_occurrence_id",
        "_segment",
        "_qc",
        "_quality_flags",
        "_sample_index",
        "_start_index",
        "_end_index",
        "_time_s",
        "_timestamp",
    )
    return tuple(
        (entry.key, entry.value)
        for entry in parameters
        if entry.key not in ignored_keys and not entry.key.endswith(ignored_suffixes)
    )


def _event_parameter_method_key_from_boundary(
    serialized_parameters: str | None,
) -> object:
    if serialized_parameters is None:
        return None
    try:
        parameters = from_canonical_json(serialized_parameters, CMJEventDetectorParameters)
    except (TypeError, ValueError):
        return ("UNPARSED", serialized_parameters)
    return _event_detector_parameter_method_key(parameters)


def _phase_boundary_method_key(boundary: CMJPhaseBoundary) -> tuple[object, ...]:
    return (
        boundary.kind,
        boundary.method.stable_id,
        boundary.source_event_definition.stable_id if boundary.source_event_definition else None,
        boundary.source_event_method.stable_id if boundary.source_event_method else None,
        _event_parameter_method_key_from_boundary(boundary.source_event_parameters),
        boundary.tie_policy,
        boundary.velocity_threshold_policy,
        boundary.interpolation_policy,
        _timebase_method_key(boundary.source_timebase),
    )


def _phase_provenance_event_method_key(
    provenance: Provenance,
) -> tuple[tuple[object, ...], ...]:
    """Recover all source event method semantics without occurrence coordinates."""

    keys: set[tuple[object, ...]] = set()
    for run in provenance.processing_runs:
        if run.method.identifier.object_type != "event-method":
            continue
        parameters = {entry.key: entry.value for entry in run.parameters}
        detector_parameters = parameters.get("detector_parameters")
        keys.add(
            (
                parameters.get("event_definition"),
                run.method.stable_id,
                _event_parameter_method_key_from_boundary(
                    detector_parameters if isinstance(detector_parameters, str) else None
                ),
            )
        )
    return tuple(sorted(keys, key=repr))


def _phase_metric_method_key(result: CMJPhaseMetricResult) -> tuple[object, ...]:
    phase = result.phase_occurrence
    return (
        result.metric,
        phase.phase_system.stable_id,
        phase.phase_definition.stable_id,
        phase.boundary_convention.stable_id,
        _phase_boundary_method_key(phase.start_boundary),
        _phase_boundary_method_key(phase.end_boundary),
        _phase_provenance_event_method_key(phase.provenance),
        phase.source_velocity_operation.stable_id,
        phase.source_velocity_integration_method.stable_id,
        _velocity_integration_method_key(phase.source_velocity_integration_interval),
        _zero_velocity_reference_method_key(phase.source_velocity_initial_condition),
        phase.source_velocity_version,
        phase.source_velocity_filtering,
        _phase_velocity_processing_method_key(phase.source_velocity_processing_parameters),
        phase.source_system_contract,
        _timebase_method_key(phase.source_velocity_measurement_identity.acquisition.timebase),
        _source_measurement_method_key(phase.source_velocity_measurement_identity),
        result.source_mechanics_quantity,
        _timebase_method_key(result.source_timebase),
        result.observation.identity.semantic.measurand.stable_id,
        result.observation.identity.semantic.metric_definition.stable_id,
        result.observation.identity.processing.registered_operation,
        result.source_mechanics_operation.stable_id,
        result.observation.identity.processing.integration_method,
        _velocity_integration_method_key(result.source_integration_interval),
        _processing_method_policy_key(result.observation.identity.processing.method_parameters),
        result.observation.identity.processing.filtering,
        result.observation.identity.processing.normalization,
        result.observation.identity.processing.trial_selection,
        result.observation.identity.processing.aggregation,
        result.observation.result.unit,
    )


def _phase_comparability_result(
    request: CMJPhaseComparabilityRequest,
    *,
    state: ComparabilityState,
    reason_codes: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=reason_codes,
        conditions=conditions,
        transformations_required=request.requested_transformations,
        missing_information=missing_information,
        rule_reference=CMJ_PHASE_COMPARABILITY_RULE,
        evidence_references=(RES39_DECISION_PHASE_COMPARABILITY_REFUSAL,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def assess_cmj_phase_comparability(
    request: CMJPhaseComparabilityRequest,
    left: CMJPhaseMetricResult,
    right: CMJPhaseMetricResult,
) -> ComparabilityResult:
    """Compare method identity without treating same-label phases as equivalent."""

    differences: list[tuple[str, str]] = []
    if left.metric is not right.metric:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "phase metric"))
    if (
        left.phase_occurrence.phase_system.stable_id
        != right.phase_occurrence.phase_system.stable_id
    ):
        differences.append((ComparabilityReasonCode.PHASE_SYSTEM_MISMATCH, "phase system"))
    if (
        left.phase_occurrence.phase_definition.stable_id
        != right.phase_occurrence.phase_definition.stable_id
    ):
        differences.append((ComparabilityReasonCode.PHASE_DEFINITION_MISMATCH, "phase definition"))
    if left.phase_occurrence.boundary_convention != right.phase_occurrence.boundary_convention:
        differences.append(
            (ComparabilityReasonCode.PHASE_BOUNDARY_CONVENTION_MISMATCH, "boundary convention")
        )
    if _phase_boundary_method_key(
        left.phase_occurrence.start_boundary
    ) != _phase_boundary_method_key(
        right.phase_occurrence.start_boundary
    ) or _phase_boundary_method_key(
        left.phase_occurrence.end_boundary
    ) != _phase_boundary_method_key(right.phase_occurrence.end_boundary):
        differences.append(
            (ComparabilityReasonCode.PHASE_BOUNDARY_METHOD_MISMATCH, "phase boundary methods")
        )
    if _phase_metric_method_key(left) != _phase_metric_method_key(right):
        differences.append(
            (ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH, "phase/upstream method identity")
        )
    source_comparison = compare_cmj_measurement_identities(
        left.phase_occurrence.source_measurement_identity,
        right.phase_occurrence.source_measurement_identity,
        claim=request.claim,
        request_id=InstanceIdentifier(
            "comparability-request", f"{request.request_id.value}:source"
        ),
        left_observation_id=left.phase_occurrence.source_observation_id,
        right_observation_id=right.phase_occurrence.source_observation_id
        if left.phase_occurrence.source_observation_id
        != right.phase_occurrence.source_observation_id
        else left.observation.observation_id,
    )
    if source_comparison.state is not ComparabilityState.COMPARABLE:
        differences.extend(
            (reason, "source acquisition") for reason in source_comparison.reason_codes
        )
    if request.requested_transformations and not differences:
        return _phase_comparability_result(
            request,
            state=ComparabilityState.REQUIRES_TRANSFORMATION,
            reason_codes=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            conditions=("the requested registered transformation must be applied first",),
        )
    reasons = tuple(dict.fromkeys(reason for reason, _ in differences))
    if not reasons:
        return _phase_comparability_result(request, state=ComparabilityState.COMPARABLE)
    if ComparabilityReasonCode.MEASURAND_MISMATCH in reasons:
        return _phase_comparability_result(
            request, state=ComparabilityState.NOT_COMPARABLE, reason_codes=reasons
        )
    return _phase_comparability_result(
        request,
        state=ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
        reason_codes=reasons,
        conditions=(
            "a registered phase-system, boundary, upstream mechanics, loading, or "
            "source bridge is required before the claim",
        ),
    )


def compare_cmj_phase_metrics(
    left: CMJPhaseMetricResult,
    right: CMJPhaseMetricResult,
    *,
    claim: str,
    request_id: InstanceIdentifier,
) -> ComparabilityResult:
    return assess_cmj_phase_comparability(
        CMJPhaseComparabilityRequest(
            request_id=request_id,
            left_observation_id=left.observation.observation_id,
            right_observation_id=right.observation.observation_id,
            claim=claim,
        ),
        left,
        right,
    )


def refusal_for_cmj_phase_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Refuse only the phase comparison while preserving both outputs."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    return _phase_refusal(
        blocked_claim,
        (RefusalReasonCode.PHASE_COMPARABILITY_UNESTABLISHED,),
        result.missing_information
        or ("registered phase-system/boundary/upstream comparability bridge",),
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


detect_peak_negative_velocity = detect_peak_negative_supported_system_com_velocity
detect_direction_change_boundary = detect_cmj_direction_change_boundary
build_cmj_phase_occurrences = construct_cmj_phase_occurrences


__all__ = [
    "CMJ_BRAKING_PHASE_DEFINITION",
    "CMJ_BRAKING_PHASE_V1",
    "CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_SPEC",
    "CMJ_PHASE_DEFINITIONS",
    "CMJ_PHASE_SYSTEM_V1",
    "CMJ_PROPULSION_PHASE_DEFINITION",
    "CMJ_PROPULSION_PHASE_V1",
    "CMJ_UNWEIGHTING_PHASE_DEFINITION",
    "CMJ_UNWEIGHTING_PHASE_V1",
    "RES39_SOFTWARE_VERSION",
    "CMJPhaseBoundary",
    "CMJPhaseBoundaryKind",
    "CMJPhaseComparabilityRequest",
    "CMJPhaseDefinition",
    "CMJPhaseLabel",
    "CMJPhaseMetric",
    "CMJPhaseMetricResult",
    "CMJPhaseOccurrence",
    "CMJPhaseSampleSupport",
    "CMJPhaseSystem",
    "assess_cmj_phase_comparability",
    "build_cmj_phase_occurrences",
    "calculate_cmj_phase_duration",
    "calculate_cmj_phase_net_vertical_impulse",
    "calculate_cmj_phase_relative_displacement_change",
    "calculate_cmj_phase_supported_system_com_relative_displacement_change",
    "compare_cmj_phase_metrics",
    "construct_cmj_phase_occurrences",
    "derive_cmj_phase_occurrences",
    "detect_cmj_direction_change_boundary",
    "detect_cmj_propulsion_onset",
    "detect_direction_change_boundary",
    "detect_peak_negative_supported_system_com_velocity",
    "detect_peak_negative_velocity",
    "refusal_for_cmj_phase_comparability",
]
