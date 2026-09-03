"""Authoritative RES-37 CMJ mechanics quantities and narrow operations.

The module deliberately stops at supported-system COM relative displacement.  It
does not create phase labels, power, RFD, or any jump-height estimator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.cmj.events import CMJEventOccurrence
from dynamislm.measurement.cmj.identity import (
    CMJ_REGISTRY_VERSION,
    CMJMeasurementIdentity,
    CMJProtocolIdentity,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL,
    CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY,
    CMJ_MECHANICS_COMPARABILITY_RULE,
    CMJ_MECHANICS_SYSTEM_CONTRACT,
    CMJ_NET_VERTICAL_FORCE_MEASURAND,
    CMJ_NET_VERTICAL_FORCE_METRIC,
    CMJ_NET_VERTICAL_FORCE_OPERATION,
    CMJ_NET_VERTICAL_FORCE_SCHEMA,
    CMJ_NET_VERTICAL_IMPULSE_MEASURAND,
    CMJ_NET_VERTICAL_IMPULSE_METRIC,
    CMJ_NET_VERTICAL_IMPULSE_OPERATION,
    CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT,
    CMJ_QUALIFIED_ZERO_VELOCITY_REFERENCE,
    CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN,
    CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_MEASURAND,
    CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_METRIC,
    CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_OPERATION,
    CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_SCHEMA,
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_MEASURAND,
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_METRIC,
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION,
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_SCHEMA,
    CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_MEASURAND,
    CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_METRIC,
    CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION,
    CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_SCHEMA,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_TRAPEZOIDAL_INTEGRATION_METHOD,
    CMJ_ZERO_INITIAL_VERTICAL_VELOCITY,
    KILOGRAM,
    METER,
    METERS_PER_SECOND,
    METERS_PER_SECOND_SQUARED,
    NEWTON,
    NEWTON_SECOND,
    RES37_DECISION_DISPLACEMENT_REFERENCE,
    RES37_DECISION_IMPULSE_INTEGRATION,
    RES37_DECISION_PHYSICAL_MASS_ACCELERATION,
    RES37_DECISION_SUPPORTED_SYSTEM_NET_FORCE,
    RES46_DECISION_QUALIFIED_ZERO_VELOCITY,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    CMJForceInput,
    PhysicalSystemMassResult,
    StandardGravityMassEquivalentResult,
    SystemWeightResult,
    TotalSupportedForceResult,
    WeighingBaselineQC,
    WeighingSegment,
    _derived_identity,
    _force_semantics_refusal,
    _input_common_refusal,
    _merge_provenance,
    _provenance_with_run,
    _weight_input_refusal,
    construct_total_supported_vertical_force,
    estimate_system_weight,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    UnitReference,
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
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES37_SOFTWARE_VERSION = "dynamislm-res37-1.0.0"
_UNCERTAINTY_NOTE = "RES-37 downstream uncertainty propagation is not assessed."


def _finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")


def _text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _id(
    value: InstanceIdentifier | ScientificIdentifier | RegistryReference | UnitReference,
) -> str:
    if isinstance(value, InstanceIdentifier):
        return value.qualified
    if isinstance(value, ScientificIdentifier):
        return value.stable_id
    if isinstance(value, RegistryReference):
        return value.stable_id
    return value.identifier.stable_id


def _unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


class CMJMechanicsQuantity(StrEnum):
    NET_VERTICAL_FORCE = "NET_VERTICAL_FORCE"
    SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION = "SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION"
    SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY = "SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY"
    SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT = (
        "SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT"
    )


class CMJIntegrationIntervalKind(StrEnum):
    EXPLICIT_SAMPLE_INTERVAL = "EXPLICIT_SAMPLE_INTERVAL"
    EVENT_BOUNDED_INTERVAL = "EVENT_BOUNDED_INTERVAL"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJMechanicalSystemContract:
    """Explicit boundary and force-completeness contract for RES-37 mechanics."""

    system_definition: RegistryReference
    external_force_model: RegistryReference
    system_description: str
    force_platform_represents_total_supported_force: bool
    gravity_is_only_other_material_vertical_external_force: bool
    composition_stable: bool
    includes_supported_external_load: bool

    def __post_init__(self) -> None:
        _text(self.system_description, "system_description")
        for field_name in (
            "force_platform_represents_total_supported_force",
            "gravity_is_only_other_material_vertical_external_force",
            "composition_stable",
            "includes_supported_external_load",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be a bool")

    @property
    def is_authorized(self) -> bool:
        return (
            self.system_definition.stable_id == CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id
            and self.external_force_model.stable_id
            == CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL.stable_id
            and self.force_platform_represents_total_supported_force
            and self.gravity_is_only_other_material_vertical_external_force
            and self.composition_stable
        )


# Readable alias; the registered wire type remains CMJMechanicalSystemContract.
MechanicalSystemContract = CMJMechanicalSystemContract


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJIntegrationInterval:
    """Inclusive sample support for one registered integration operation."""

    source_signal_id: InstanceIdentifier
    start_index: int
    end_index: int
    kind: CMJIntegrationIntervalKind = CMJIntegrationIntervalKind.EXPLICIT_SAMPLE_INTERVAL
    boundary_convention: RegistryReference = CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY
    integration_method: RegistryReference = CMJ_TRAPEZOIDAL_INTEGRATION_METHOD
    start_event: CMJEventOccurrence | None = None
    end_event: CMJEventOccurrence | None = None

    def __post_init__(self) -> None:
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("interval source_signal_id must identify a signal")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("interval indices must be integers")
        if self.start_index < 0 or self.end_index < self.start_index:
            raise ValueError("interval must satisfy 0 <= start_index <= end_index")
        if not isinstance(self.kind, CMJIntegrationIntervalKind):
            raise ValueError("interval kind must be registered")
        if (
            self.boundary_convention.stable_id
            != CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY.stable_id
        ):
            raise ValueError("RES-37 requires inclusive endpoint-sample integration")
        if self.integration_method.stable_id != CMJ_TRAPEZOIDAL_INTEGRATION_METHOD.stable_id:
            raise ValueError("interval requires the registered trapezoidal integration method")
        events = (self.start_event, self.end_event)
        if self.kind is CMJIntegrationIntervalKind.EXPLICIT_SAMPLE_INTERVAL and any(events):
            raise ValueError("explicit sample interval cannot contain event bounds")
        if self.kind is CMJIntegrationIntervalKind.EVENT_BOUNDED_INTERVAL and not any(events):
            raise ValueError("event-bounded interval requires an event bound")
        if self.start_event is not None:
            self._validate_event(self.start_event, self.start_index, "start_event")
        if self.end_event is not None:
            self._validate_event(self.end_event, self.end_index, "end_event")

    def _validate_event(self, event: CMJEventOccurrence, index: int, field_name: str) -> None:
        if event.source_signal_id != self.source_signal_id:
            raise ValueError(f"{field_name} source signal does not match interval")
        if event.sample_index != index:
            raise ValueError(f"{field_name} sample does not match interval boundary")

    @classmethod
    def explicit_sample(
        cls,
        source_signal_id: InstanceIdentifier,
        start_index: int,
        end_index: int,
    ) -> CMJIntegrationInterval:
        return cls(source_signal_id, start_index, end_index)

    @classmethod
    def event_bounded(
        cls,
        *,
        start_event: CMJEventOccurrence | None = None,
        end_event: CMJEventOccurrence | None = None,
    ) -> CMJIntegrationInterval:
        events = tuple(event for event in (start_event, end_event) if event is not None)
        if not events:
            raise ValueError("event-bounded interval requires an event bound")
        source_signal_id = events[0].source_signal_id
        if any(event.source_signal_id != source_signal_id for event in events):
            raise ValueError("event bounds must share a source signal")
        start_index = start_event.sample_index if start_event is not None else 0
        end_index = end_event.sample_index if end_event is not None else start_index
        return cls(
            source_signal_id=source_signal_id,
            start_index=start_index,
            end_index=end_index,
            kind=CMJIntegrationIntervalKind.EVENT_BOUNDED_INTERVAL,
            start_event=start_event,
            end_event=end_event,
        )

    @property
    def interval_semantics(self) -> str:
        return "[start_index, end_index] inclusive; endpoint sample included; no interpolation"

    @property
    def event_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(
            event.occurrence_id for event in (self.start_event, self.end_event) if event is not None
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class InitialVelocityCondition:
    """Legacy explicit initial condition; never authoritative physical zero velocity.

    The type remains registered so strict serialization can represent and reject
    historical RES-37 payloads without silently reinterpreting them. The
    authoritative velocity operation requires QualifiedZeroVelocityReference.
    """

    source_signal_id: InstanceIdentifier
    sample_index: int
    value_m_per_s: float = 0.0
    unit: UnitReference = METERS_PER_SECOND
    method: RegistryReference = CMJ_ZERO_INITIAL_VERTICAL_VELOCITY
    reference_event: CMJEventOccurrence | None = None
    assumption: str = (
        "zero vertical velocity is an explicit operational reference at the supplied sample"
    )

    def __post_init__(self) -> None:
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("initial condition source_signal_id must identify a signal")
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise ValueError("initial condition sample_index must be nonnegative")
        _finite(self.value_m_per_s, "initial velocity")
        if self.unit.identifier.stable_id != METERS_PER_SECOND.identifier.stable_id:
            raise ValueError("initial velocity requires m/s")
        if self.method.stable_id != CMJ_ZERO_INITIAL_VERTICAL_VELOCITY.stable_id:
            raise ValueError("only the registered zero initial-velocity condition is authorized")
        if self.value_m_per_s != 0.0:
            raise ValueError("the registered RES-37 initial velocity condition is exactly zero")
        _text(self.assumption, "assumption")
        if self.reference_event is not None:
            if self.reference_event.source_signal_id != self.source_signal_id:
                raise ValueError("initial-condition event source signal does not match")
            if self.reference_event.sample_index != self.sample_index:
                raise ValueError("initial-condition event sample does not match")

    @classmethod
    def zero_at_sample(
        cls,
        source_signal_id: InstanceIdentifier,
        sample_index: int,
        *,
        reference_event: CMJEventOccurrence | None = None,
    ) -> InitialVelocityCondition:
        return cls(source_signal_id, sample_index, reference_event=reference_event)

    @property
    def reference_event_id(self) -> InstanceIdentifier | None:
        return self.reference_event.occurrence_id if self.reference_event is not None else None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualifiedZeroVelocityReference:
    """Typed RES-46 authority for a zero-velocity integration start.

    The source segment is the exact RES-35 weighing segment used to derive the
    linked SYSTEM_WEIGHT observation. This object carries identity and method
    metadata; the velocity operation still verifies that the linkage is present
    in the acceleration provenance.
    """

    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_system_weight_observation_id: InstanceIdentifier
    weighing_segment: WeighingSegment
    sample_index: int
    weighing_qc: WeighingBaselineQC
    value_m_per_s: float = 0.0
    unit: UnitReference = METERS_PER_SECOND
    method: RegistryReference = CMJ_QUALIFIED_ZERO_VELOCITY_REFERENCE
    evidence_decision: RegistryReference = RES46_DECISION_QUALIFIED_ZERO_VELOCITY

    def __post_init__(self) -> None:
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("qualified zero-velocity source_signal_id must identify a signal")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("qualified zero-velocity source_artifact_id must identify an artifact")
        if self.source_system_weight_observation_id.instance_type != "observation":
            raise ValueError(
                "qualified zero-velocity source SYSTEM_WEIGHT must identify an observation"
            )
        if not isinstance(self.weighing_segment, WeighingSegment):
            raise ValueError("qualified zero-velocity reference requires a WeighingSegment")
        if not isinstance(self.weighing_qc, WeighingBaselineQC):
            raise ValueError("qualified zero-velocity reference requires weighing baseline QC")
        if (
            self.weighing_segment.source_signal_id != self.source_signal_id
            or self.weighing_segment.source_artifact_id != self.source_artifact_id
            or self.weighing_segment.source_measurement_identity_id
            != self.source_measurement_identity_id
        ):
            raise ValueError("qualified zero-velocity source linkage must match its segment")
        if self.weighing_qc.sample_count != self.weighing_segment.sample_count:
            raise ValueError("qualified zero-velocity QC must describe the exact weighing segment")
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise ValueError("qualified zero-velocity sample_index must be nonnegative")
        if not (
            self.weighing_segment.start_index <= self.sample_index < self.weighing_segment.end_index
        ):
            raise ValueError("qualified zero-velocity sample must lie inside the weighing segment")
        _finite(self.value_m_per_s, "qualified zero-velocity value")
        if self.value_m_per_s != 0.0:
            raise ValueError("qualified zero-velocity value must be exactly zero")
        if self.unit.identifier.stable_id != METERS_PER_SECOND.identifier.stable_id:
            raise ValueError("qualified zero-velocity reference requires m/s")
        if self.method.stable_id != CMJ_QUALIFIED_ZERO_VELOCITY_REFERENCE.stable_id:
            raise ValueError("qualified zero-velocity method is not registered")
        if self.evidence_decision.stable_id != RES46_DECISION_QUALIFIED_ZERO_VELOCITY.stable_id:
            raise ValueError("qualified zero-velocity evidence decision is not registered")

    @property
    def is_authorized(self) -> bool:
        """Whether the linked RES-35 baseline has an explicit adjudication."""

        return self.weighing_qc.acceptability_adjudicated

    @classmethod
    def from_system_weight(
        cls,
        system_weight: SystemWeightResult,
        sample_index: int,
    ) -> QualifiedZeroVelocityReference:
        """Derive the reference from one exact RES-35 SYSTEM_WEIGHT result."""

        if not isinstance(system_weight, SystemWeightResult):
            raise TypeError("qualified zero-velocity reference requires SystemWeightResult")
        if system_weight.observation.result.quality.flags != system_weight.qc.quality_flags:
            raise ValueError(
                "qualified zero-velocity reference requires QC flags linked to the SYSTEM_WEIGHT"
            )
        segment = system_weight.segment
        return cls(
            source_signal_id=segment.source_signal_id,
            source_artifact_id=segment.source_artifact_id,
            source_measurement_identity_id=segment.source_measurement_identity_id,
            source_system_weight_observation_id=system_weight.observation.observation_id,
            weighing_segment=segment,
            sample_index=sample_index,
            weighing_qc=system_weight.qc,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DisplacementOrigin:
    """A relative coordinate origin, never an anatomical COM height."""

    source_velocity_series_id: InstanceIdentifier
    sample_index: int
    value_m: float = 0.0
    unit: UnitReference = METER
    method: RegistryReference = CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN
    coordinate_reference: str = (
        "relative vertical coordinate origin; not anatomical COM height zero"
    )
    reference_event: CMJEventOccurrence | None = None

    def __post_init__(self) -> None:
        if self.source_velocity_series_id.instance_type != "signal":
            raise ValueError("displacement origin must identify a velocity signal")
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise ValueError("displacement origin sample_index must be nonnegative")
        _finite(self.value_m, "displacement origin")
        if self.unit.identifier.stable_id != METER.identifier.stable_id:
            raise ValueError("displacement origin requires m")
        if self.method.stable_id != CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN.stable_id:
            raise ValueError("only the registered relative displacement origin is authorized")
        if self.value_m != 0.0:
            raise ValueError("the registered RES-37 displacement origin is exactly zero")
        _text(self.coordinate_reference, "coordinate_reference")

    @classmethod
    def zero_at_velocity_start(
        cls,
        source_velocity_series_id: InstanceIdentifier,
        sample_index: int,
        *,
        reference_event: CMJEventOccurrence | None = None,
    ) -> DisplacementOrigin:
        return cls(
            source_velocity_series_id,
            sample_index,
            reference_event=reference_event,
        )

    @property
    def reference_event_id(self) -> InstanceIdentifier | None:
        return self.reference_event.occurrence_id if self.reference_event is not None else None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJMechanicsSeries:
    """Typed, source-indexed mechanics series stored behind an output artifact."""

    series_id: InstanceIdentifier
    quantity: CMJMechanicsQuantity
    artifact_id: InstanceIdentifier
    schema: RegistryReference
    source_signal_ids: tuple[InstanceIdentifier, ...]
    source_observation_ids: tuple[InstanceIdentifier, ...]
    source_entity_ids: tuple[InstanceIdentifier, ...]
    source_artifact_ids: tuple[InstanceIdentifier, ...]
    source_measurement_identity_ids: tuple[ScientificIdentifier, ...]
    processing_run_id: InstanceIdentifier
    source_sample_count: int
    sample_start_index: int
    samples: tuple[float, ...]
    timebase: SignalTimebase
    unit: UnitReference
    physical_axis: RegistryReference
    reference_frame: RegistryReference
    sign_convention: SignConvention
    operation: RegistryReference
    system_contract: CMJMechanicalSystemContract
    integration_method: RegistryReference | None = None
    integration_interval: CMJIntegrationInterval | None = None
    initial_velocity_condition: QualifiedZeroVelocityReference | None = None
    displacement_origin: DisplacementOrigin | None = None
    source_event_ids: tuple[InstanceIdentifier, ...] = ()

    def __post_init__(self) -> None:
        if self.series_id.instance_type != "signal":
            raise ValueError("mechanics series ID must have instance_type signal")
        if self.artifact_id.instance_type != "artifact":
            raise ValueError("mechanics series artifact ID must have instance_type artifact")
        if self.processing_run_id.instance_type != "processing-run":
            raise ValueError("mechanics series processing_run_id must be a processing run")
        if not isinstance(self.quantity, CMJMechanicsQuantity):
            raise ValueError("mechanics quantity must be registered")
        for field_name, value in (
            ("source_signal_ids", self.source_signal_ids),
            ("source_observation_ids", self.source_observation_ids),
            ("source_entity_ids", self.source_entity_ids),
            ("source_artifact_ids", self.source_artifact_ids),
            ("source_measurement_identity_ids", self.source_measurement_identity_ids),
            ("source_event_ids", self.source_event_ids),
            ("samples", self.samples),
        ):
            require_tuple(value, field_name)
        if not self.source_signal_ids or not self.source_observation_ids:
            raise ValueError("mechanics series must preserve source signal and observation IDs")
        if not self.source_artifact_ids or not self.source_measurement_identity_ids:
            raise ValueError("mechanics series must preserve source artifact and identity IDs")
        if any(item.instance_type != "signal" for item in self.source_signal_ids):
            raise ValueError("source_signal_ids must identify signals")
        if any(item.instance_type != "observation" for item in self.source_observation_ids):
            raise ValueError("source_observation_ids must identify observations")
        if any(item.instance_type != "artifact" for item in self.source_artifact_ids):
            raise ValueError("source_artifact_ids must identify artifacts")
        if any(item.instance_type != "event-occurrence" for item in self.source_event_ids):
            raise ValueError("source_event_ids must identify event occurrences")
        if any(item not in self.source_entity_ids for item in self.source_observation_ids):
            raise ValueError("source observations must also be source entities")
        if any(item not in self.source_entity_ids for item in self.source_signal_ids):
            raise ValueError("source signals must also be source entities")
        if any(item not in self.source_entity_ids for item in self.source_event_ids):
            raise ValueError("source events must also be source entities")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("source_sample_count must be positive")
        if type(self.sample_start_index) is not int or self.sample_start_index < 0:
            raise ValueError("sample_start_index must be nonnegative")
        if not self.samples:
            raise ValueError("mechanics series must contain samples")
        if self.sample_start_index + len(self.samples) > self.source_sample_count:
            raise ValueError("mechanics series exceeds source sample support")
        for sample in self.samples:
            _finite(sample, "mechanics series sample")
        if isinstance(self.timebase, ExplicitTimebase):
            if len(self.timebase.times_s) != self.source_sample_count:
                raise ValueError("explicit timebase count must equal source sample count")
            previous: float | None = None
            for timestamp in self.timebase.times_s:
                _finite(timestamp, "timebase timestamp")
                if previous is not None and timestamp <= previous:
                    raise ValueError("explicit timebase timestamps must increase")
                previous = timestamp
        elif not isinstance(self.timebase, RegularTimebase):
            raise ValueError("mechanics series requires a registered timebase")
        if self.sign_convention.positive_direction != "upward":
            raise ValueError("mechanics series must be upward-positive")
        if self.operation.identifier.object_type != "registered-operation":
            raise ValueError("mechanics series operation must be registered")
        expected_operation, expected_schema, _, expected_unit = _expected_quantity_metadata(
            self.quantity
        )
        if self.operation.stable_id != expected_operation.stable_id:
            raise ValueError("mechanics series operation does not match its quantity")
        if self.schema.stable_id != expected_schema.stable_id:
            raise ValueError("mechanics series schema does not match its quantity")
        if self.unit.identifier.stable_id != expected_unit.identifier.stable_id:
            raise ValueError("mechanics series unit does not match its quantity")
        if not self.system_contract.is_authorized:
            raise ValueError("mechanics series requires an authorized system contract")
        if self.quantity in {
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
        }:
            integration_method = self.integration_method
            interval = self.integration_interval
            if integration_method is None or interval is None:
                raise ValueError("cumulative mechanics series must preserve integration identity")
            if interval.source_signal_id not in self.source_signal_ids:
                raise ValueError("integration interval must link to a source signal")
            if (
                interval.start_index < self.sample_start_index
                or interval.end_index >= self.source_sample_count
                or interval.end_index - interval.start_index + 1 != len(self.samples)
            ):
                raise ValueError("integration interval must exactly cover the series samples")
            if interval.integration_method.stable_id != integration_method.stable_id:
                raise ValueError("series and interval integration methods must match")
            if any(event_id not in self.source_event_ids for event_id in interval.event_ids):
                raise ValueError("integration interval events must be preserved by the series")
        if self.quantity is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY:
            initial_condition = self.initial_velocity_condition
            interval = self.integration_interval
            if (
                initial_condition is None
                or interval is None
                or self.displacement_origin is not None
            ):
                raise ValueError(
                    "velocity series must preserve only its initial velocity condition"
                )
            if not isinstance(initial_condition, QualifiedZeroVelocityReference):
                raise ValueError(
                    "velocity series must preserve a qualified zero-velocity reference"
                )
            if not initial_condition.is_authorized:
                raise ValueError(
                    "velocity series requires adjudicated zero-velocity reference authority"
                )
            if (
                initial_condition.source_signal_id not in self.source_signal_ids
                or initial_condition.source_artifact_id not in self.source_artifact_ids
                or initial_condition.source_measurement_identity_id
                not in self.source_measurement_identity_ids
                or initial_condition.source_system_weight_observation_id
                not in self.source_observation_ids
            ):
                raise ValueError("velocity series must preserve exact zero-velocity source linkage")
            if initial_condition.sample_index != interval.start_index:
                raise ValueError("velocity initial condition must match interval start")
        if (
            self.quantity
            is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT
        ):
            initial_condition = self.initial_velocity_condition
            interval = self.integration_interval
            if (
                self.displacement_origin is None
                or interval is None
                or not isinstance(initial_condition, QualifiedZeroVelocityReference)
            ):
                raise ValueError(
                    "displacement series must preserve its origin and qualified velocity authority"
                )
            if not initial_condition.is_authorized:
                raise ValueError(
                    "displacement series requires adjudicated zero-velocity reference authority"
                )
            if (
                initial_condition.source_signal_id not in self.source_signal_ids
                or initial_condition.source_artifact_id not in self.source_artifact_ids
                or initial_condition.source_measurement_identity_id
                not in self.source_measurement_identity_ids
                or initial_condition.source_system_weight_observation_id
                not in self.source_observation_ids
                or initial_condition.sample_index != interval.start_index
            ):
                raise ValueError(
                    "displacement series must preserve exact zero-velocity source linkage"
                )
            if (
                self.displacement_origin.source_velocity_series_id != self.source_signal_ids[0]
                or self.displacement_origin.sample_index != self.sample_start_index
            ):
                raise ValueError("displacement origin must match the series start")
            if (
                self.displacement_origin.reference_event_id is not None
                and self.displacement_origin.reference_event_id not in self.source_event_ids
            ):
                raise ValueError("displacement-origin event must be preserved")
        if self.quantity in {
            CMJMechanicsQuantity.NET_VERTICAL_FORCE,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION,
        } and any(
            value is not None
            for value in (
                self.integration_method,
                self.integration_interval,
                self.initial_velocity_condition,
                self.displacement_origin,
            )
        ):
            raise ValueError("non-cumulative mechanics series cannot carry cumulative conditions")

    @property
    def source_sample_indices(self) -> tuple[int, ...]:
        return tuple(range(self.sample_start_index, self.sample_start_index + len(self.samples)))

    @property
    def source_signal_id(self) -> InstanceIdentifier:
        return self.source_signal_ids[0]


def _expected_quantity_metadata(
    quantity: CMJMechanicsQuantity,
) -> tuple[RegistryReference, RegistryReference, RegistryReference, UnitReference]:
    if quantity is CMJMechanicsQuantity.NET_VERTICAL_FORCE:
        return (
            CMJ_NET_VERTICAL_FORCE_OPERATION,
            CMJ_NET_VERTICAL_FORCE_SCHEMA,
            CMJ_NET_VERTICAL_FORCE_METRIC,
            NEWTON,
        )
    if quantity is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION:
        return (
            CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_OPERATION,
            CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_SCHEMA,
            CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_METRIC,
            METERS_PER_SECOND_SQUARED,
        )
    if quantity is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY:
        return (
            CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION,
            CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_SCHEMA,
            CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_METRIC,
            METERS_PER_SECOND,
        )
    return (
        CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION,
        CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_SCHEMA,
        CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_METRIC,
        METER,
    )


def _expected_measurand(quantity: CMJMechanicsQuantity) -> RegistryReference:
    if quantity is CMJMechanicsQuantity.NET_VERTICAL_FORCE:
        return CMJ_NET_VERTICAL_FORCE_MEASURAND
    if quantity is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION:
        return CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_MEASURAND
    if quantity is CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY:
        return CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_MEASURAND
    return CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_MEASURAND


def _validate_series_observation(
    observation: ScientificMeasurementObservation,
    series: CMJMechanicsSeries,
    quantity: CMJMechanicsQuantity,
) -> None:
    operation, schema, metric, unit = _expected_quantity_metadata(quantity)
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("mechanics observation requires a CMJ measurement identity")
    if identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
        raise ValueError("mechanics observation must use the supported-system construct")
    if identity.semantic.metric_definition.stable_id != metric.stable_id:
        raise ValueError("mechanics observation has the wrong metric identity")
    if identity.processing.registered_operation is None or (
        identity.processing.registered_operation.stable_id != operation.stable_id
    ):
        raise ValueError("mechanics observation has the wrong operation identity")
    if (
        observation.result.unit is None
        or observation.result.unit.identifier.stable_id != unit.identifier.stable_id
    ):
        raise ValueError("mechanics observation has the wrong unit")
    value = observation.result.value
    if not isinstance(value, StructuredOutputReference) or value.artifact_id != series.artifact_id:
        raise ValueError("mechanics observation must reference its mechanics artifact")
    if value.schema.stable_id != schema.stable_id:
        raise ValueError("mechanics observation must reference its mechanics schema")
    if series.quantity is not quantity:
        raise ValueError("mechanics result series quantity mismatch")
    matching_runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.processing_run_id == series.processing_run_id
        and run.output_entity_id == observation.observation_id
    )
    if len(matching_runs) != 1:
        raise ValueError("mechanics observation must preserve one matching processing run")
    if matching_runs[0].parameters != identity.processing.method_parameters:
        raise ValueError("mechanics processing run parameters must match observation identity")
    if quantity in {
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
    }:
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if parameters.get("zero_velocity_reference") != canonical_json(
            series.initial_velocity_condition
        ):
            raise ValueError("mechanics observation must preserve its zero-velocity reference")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class NetVerticalForceResult:
    observation: ScientificMeasurementObservation
    series: CMJMechanicsSeries
    source_system_weight_observation_id: InstanceIdentifier

    def __post_init__(self) -> None:
        _validate_series_observation(
            self.observation, self.series, CMJMechanicsQuantity.NET_VERTICAL_FORCE
        )
        if self.source_system_weight_observation_id not in self.series.source_observation_ids:
            raise ValueError("net force must preserve its source SYSTEM_WEIGHT observation")

    @property
    def samples(self) -> tuple[float, ...]:
        return self.series.samples

    @property
    def timebase(self) -> SignalTimebase:
        return self.series.timebase

    @property
    def unit(self) -> UnitReference:
        return self.series.unit

    @property
    def system_contract(self) -> CMJMechanicalSystemContract:
        return self.series.system_contract


@register_serializable_type
@dataclass(frozen=True, slots=True)
class NetVerticalImpulseResult:
    observation: ScientificMeasurementObservation
    interval: CMJIntegrationInterval
    source_net_force_series_id: InstanceIdentifier
    source_system_weight_observation_id: InstanceIdentifier
    system_contract: CMJMechanicalSystemContract
    timebase: SignalTimebase

    def __post_init__(self) -> None:
        identity = self.observation.identity
        if not isinstance(identity, CMJMeasurementIdentity):
            raise ValueError("impulse observation requires a CMJ measurement identity")
        if identity.semantic.measurand.stable_id != CMJ_NET_VERTICAL_IMPULSE_MEASURAND.stable_id:
            raise ValueError("impulse observation has the wrong measurand")
        if (
            identity.semantic.metric_definition.stable_id
            != CMJ_NET_VERTICAL_IMPULSE_METRIC.stable_id
        ):
            raise ValueError("impulse observation has the wrong metric")
        if identity.processing.registered_operation is None or (
            identity.processing.registered_operation.stable_id
            != CMJ_NET_VERTICAL_IMPULSE_OPERATION.stable_id
        ):
            raise ValueError("impulse observation has the wrong operation")
        if identity.processing.integration_method is None or (
            identity.processing.integration_method.stable_id
            != CMJ_TRAPEZOIDAL_INTEGRATION_METHOD.stable_id
        ):
            raise ValueError("impulse observation must preserve its integration method")
        if self.observation.result.unit is None or (
            self.observation.result.unit.identifier.stable_id != NEWTON_SECOND.identifier.stable_id
        ):
            raise ValueError("impulse observation must use N·s")
        if not isinstance(self.observation.result.value, ScalarValue):
            raise ValueError("impulse observation must contain a scalar")
        if self.source_net_force_series_id.instance_type != "signal":
            raise ValueError("impulse source must identify a net-force signal")
        if self.source_system_weight_observation_id.instance_type != "observation":
            raise ValueError("impulse source SYSTEM_WEIGHT must identify an observation")
        if not self.system_contract.is_authorized:
            raise ValueError("impulse requires an authorized system contract")
        if not isinstance(self.timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("impulse requires a registered source timebase")
        parameters = {
            entry.key: entry.value
            for entry in self.observation.identity.processing.method_parameters
        }
        if (
            parameters.get("source_net_force_series_id")
            != self.source_net_force_series_id.qualified
            or parameters.get("source_system_weight_observation_id")
            != self.source_system_weight_observation_id.qualified
            or parameters.get("source_timebase") != canonical_json(self.timebase)
            or parameters.get("system_contract") != canonical_json(self.system_contract)
        ):
            raise ValueError("impulse source linkage does not match its processing metadata")

    @property
    def value_ns(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("impulse result is not numeric")
        return float(value.value)

    @property
    def unit(self) -> UnitReference:
        unit = self.observation.result.unit
        if unit is None:
            raise ValueError("impulse result has no unit")
        return unit


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SupportedSystemComAccelerationResult:
    observation: ScientificMeasurementObservation
    series: CMJMechanicsSeries
    source_physical_system_mass_observation_id: InstanceIdentifier
    source_system_weight_observation_id: InstanceIdentifier

    def __post_init__(self) -> None:
        _validate_series_observation(
            self.observation,
            self.series,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION,
        )
        if (
            self.source_physical_system_mass_observation_id
            not in self.series.source_observation_ids
        ):
            raise ValueError("acceleration must preserve its physical mass observation")
        if self.source_system_weight_observation_id not in self.series.source_observation_ids:
            raise ValueError("acceleration must preserve its SYSTEM_WEIGHT observation")

    @property
    def samples(self) -> tuple[float, ...]:
        return self.series.samples

    @property
    def system_contract(self) -> CMJMechanicalSystemContract:
        return self.series.system_contract


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SupportedSystemComVelocityResult:
    observation: ScientificMeasurementObservation
    series: CMJMechanicsSeries
    initial_velocity_condition: QualifiedZeroVelocityReference

    def __post_init__(self) -> None:
        _validate_series_observation(
            self.observation,
            self.series,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
        )
        if self.series.initial_velocity_condition != self.initial_velocity_condition:
            raise ValueError("velocity result initial condition must match its series")

    @property
    def samples(self) -> tuple[float, ...]:
        return self.series.samples

    @property
    def system_contract(self) -> CMJMechanicalSystemContract:
        return self.series.system_contract


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SupportedSystemComRelativeDisplacementResult:
    observation: ScientificMeasurementObservation
    series: CMJMechanicsSeries
    displacement_origin: DisplacementOrigin

    def __post_init__(self) -> None:
        _validate_series_observation(
            self.observation,
            self.series,
            CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
        )
        if self.series.displacement_origin != self.displacement_origin:
            raise ValueError("displacement result origin must match its series")
        parameters = {
            entry.key: entry.value
            for entry in self.observation.identity.processing.method_parameters
        }
        source_velocity_observation_id = parameters.get("source_velocity_observation_id")
        source_velocity_runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id.qualified == source_velocity_observation_id
        )
        if (
            len(source_velocity_runs) != 1
            or dict((entry.key, entry.value) for entry in source_velocity_runs[0].parameters).get(
                "zero_velocity_reference"
            )
            != canonical_json(self.series.initial_velocity_condition)
            or parameters.get("source_velocity_initial_condition_semantics")
            != canonical_json(_condition_key(self.series.initial_velocity_condition))
        ):
            raise ValueError("displacement must preserve its upstream velocity authority")

    @property
    def samples(self) -> tuple[float, ...]:
        return self.series.samples

    @property
    def system_contract(self) -> CMJMechanicalSystemContract:
        return self.series.system_contract


MechanicsResult = (
    NetVerticalForceResult
    | NetVerticalImpulseResult
    | SupportedSystemComAccelerationResult
    | SupportedSystemComVelocityResult
    | SupportedSystemComRelativeDisplacementResult
)


def _mechanics_refusal(
    blocked_claim: str,
    reasons: tuple[RefusalReasonCode, ...],
    missing: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    reason_values = tuple(reason.value for reason in reasons)
    key = canonical_hash(
        {
            "mission": "RES37",
            "blocked_claim": blocked_claim,
            "reasons": reason_values,
            "missing": missing,
            "observations": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res37:{key}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=reason_values,
        missing_information=missing,
        what_can_still_be_safely_described=(
            "valid upstream force, weight, mass, or mechanics results remain "
            "independently describable",
            "no athlete-COM, phase, power, RFD, or jump-height claim is emitted",
        ),
        observation_ids=observation_ids,
    )


def _obs_ids(
    values: tuple[ScientificMeasurementObservation, ...],
) -> tuple[InstanceIdentifier, ...]:
    return _unique(tuple(value.observation_id for value in values))


def _cmj_observation_identity(
    observation: ScientificMeasurementObservation,
) -> CMJMeasurementIdentity:
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("mechanics operation requires a CMJ measurement identity")
    return identity


def _event_values(
    interval: CMJIntegrationInterval | None = None,
    condition: QualifiedZeroVelocityReference | InitialVelocityCondition | None = None,
    origin: DisplacementOrigin | None = None,
) -> tuple[CMJEventOccurrence, ...]:
    values: list[CMJEventOccurrence] = []
    if interval is not None:
        values.extend(
            event for event in (interval.start_event, interval.end_event) if event is not None
        )
    if isinstance(condition, InitialVelocityCondition) and condition.reference_event is not None:
        values.append(condition.reference_event)
    if origin is not None and origin.reference_event is not None:
        values.append(origin.reference_event)
    return _unique(tuple(values))


def _merge_sources(
    observations: tuple[ScientificMeasurementObservation, ...],
    events: tuple[CMJEventOccurrence, ...],
) -> Provenance:
    if not observations:
        raise ValueError("at least one source observation is required")
    merged = observations[0].provenance
    for observation in observations[1:]:
        merged = _merge_provenance(merged, observation.provenance)
    for event in events:
        merged = _merge_provenance(merged, event.provenance)
    return merged


def _event_observation_ids(
    events: tuple[CMJEventOccurrence, ...],
) -> tuple[InstanceIdentifier, ...]:
    return _unique(tuple(event.source_observation_id for event in events))


def _event_identity_ids(events: tuple[CMJEventOccurrence, ...]) -> tuple[ScientificIdentifier, ...]:
    return _unique(tuple(event.source_measurement_identity.identity_id for event in events))


def _sample_delta(timebase: SignalTimebase, left_index: int, right_index: int) -> float:
    if isinstance(timebase, RegularTimebase):
        return (right_index - left_index) / timebase.sample_rate_hz
    if isinstance(timebase, ExplicitTimebase):
        return timebase.times_s[right_index] - timebase.times_s[left_index]
    raise ValueError("registered timebase required")


def _validate_timebase(timebase: SignalTimebase, sample_count: int) -> RefusalReasonCode | None:
    if isinstance(timebase, RegularTimebase):
        return None
    if not isinstance(timebase, ExplicitTimebase) or len(timebase.times_s) != sample_count:
        return RefusalReasonCode.TIMEBASE_INSUFFICIENT
    previous: float | None = None
    for timestamp in timebase.times_s:
        if not math.isfinite(timestamp) or (previous is not None and timestamp <= previous):
            return RefusalReasonCode.INVALID_TIMEBASE
        previous = timestamp
    return None


def _validate_contract(
    contract: CMJMechanicalSystemContract | None,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
    *,
    protocol: CMJProtocolIdentity | None = None,
) -> RefusalResult | None:
    if contract is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED,),
            ("explicit CMJ supported-system mechanics contract",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    reasons: list[RefusalReasonCode] = []
    missing: list[str] = []
    if contract.system_definition.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
        reasons.append(RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED)
        missing.append("CMJ_SUPPORTED_SYSTEM_CONSTRUCT system definition")
    if (
        contract.external_force_model.stable_id
        != CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL.stable_id
    ):
        reasons.append(RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED)
        missing.append("registered force-platform-plus-gravity external-force model")
    if not contract.force_platform_represents_total_supported_force:
        reasons.append(RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED)
        missing.append("force platform represents the total supported vertical force")
    if not contract.gravity_is_only_other_material_vertical_external_force:
        reasons.append(RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED)
        missing.append("gravity is the only other material vertical external force")
    if not contract.composition_stable:
        reasons.append(RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED)
        missing.append("stable supported-system composition")
    if protocol is None or protocol.external_loading is None:
        reasons.append(RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED)
        missing.append("resolved protocol external-loading attribute for audit")
    if reasons:
        return _mechanics_refusal(
            claim,
            tuple(_unique(tuple(reasons))),
            tuple(_unique(tuple(missing))),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _resolve_total_force(
    force: TotalSupportedForceResult | CMJForceInput,
    counterpart: CMJForceInput | None,
    claim: str,
) -> tuple[TotalSupportedForceResult | None, RefusalResult | None]:
    if isinstance(force, TotalSupportedForceResult):
        if counterpart is not None:
            return None, _mechanics_refusal(
                claim,
                (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
                ("counterpart is not accepted after total-force construction",),
            )
        return force, None
    if isinstance(force, CMJForceInput):
        result = construct_total_supported_vertical_force(force, counterpart)
        if isinstance(result, RefusalResult):
            return None, result
        return result, None
    return None, _mechanics_refusal(
        claim,
        (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
        ("RES-35 TotalSupportedForceResult",),
    )


def _force_refusal(
    force: TotalSupportedForceResult,
    claim: str,
) -> tuple[CMJForceInput | None, RefusalResult | None]:
    force_input = force.as_force_input()
    source_refusal = _input_common_refusal(force_input, claim)
    if source_refusal is not None:
        return None, source_refusal
    semantics_refusal = _force_semantics_refusal(force_input, claim)
    if semantics_refusal is not None:
        return None, semantics_refusal
    if (
        force_input.signal.unit is None
        or force_input.signal.unit.identifier.stable_id != NEWTON.identifier.stable_id
    ):
        return None, _mechanics_refusal(
            claim,
            (RefusalReasonCode.FORCE_UNIT_TRANSFORMATION_REQUIRED,),
            ("canonical Newton total supported force; no RES-37 unit conversion is registered",),
            (force_input.observation.observation_id,),
        )
    if force_input.observation.result.status is not ResultStatus.VALID:
        return None, _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("valid total supported force observation",),
            (force_input.observation.observation_id,),
        )
    timebase = force_input.signal.timebase
    if timebase is None:
        return None, _mechanics_refusal(
            claim,
            (RefusalReasonCode.TIMEBASE_INSUFFICIENT,),
            ("valid total supported force timebase",),
            (force_input.observation.observation_id,),
        )
    timebase_reason = _validate_timebase(timebase, len(force_input.signal.samples))
    if timebase_reason is not None:
        return None, _mechanics_refusal(
            claim,
            (timebase_reason,),
            ("valid total supported force timebase",),
            (force_input.observation.observation_id,),
        )
    return force_input, None


def _weight_refusal(
    force_input: CMJForceInput,
    weight: SystemWeightResult | None,
    claim: str,
) -> RefusalResult | None:
    observation_ids: tuple[InstanceIdentifier, ...] = (force_input.observation.observation_id,)
    if weight is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SYSTEM_WEIGHT_REQUIRED,),
            ("exact compatible RES-35 SystemWeightResult",),
            observation_ids,
        )
    if not isinstance(weight, SystemWeightResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SYSTEM_WEIGHT_REQUIRED,),
            ("RES-35 SystemWeightResult, not an untyped scalar",),
            observation_ids,
        )
    observation_ids = (*observation_ids, weight.observation.observation_id)
    lineage_refusal = _weight_input_refusal(weight.observation, claim)
    if lineage_refusal is not None:
        return lineage_refusal
    weight_identity = weight.observation.identity
    if not isinstance(weight_identity, CMJMeasurementIdentity):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.FORCE_WEIGHT_SYSTEM_MISMATCH,),
            ("CMJ SYSTEM_WEIGHT identity",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if weight_identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.FORCE_WEIGHT_SYSTEM_MISMATCH,),
            ("SYSTEM_WEIGHT supported-system identity",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        weight.segment.source_signal_id != force_input.signal.signal_id
        or weight.segment.source_artifact_id != force_input.source_artifact.artifact_id
        or weight.segment.source_measurement_identity_id != force_input.identity.identity_id
        or weight.observation.context != force_input.observation.context
        or weight_identity.semantic.protocol_identity
        != force_input.identity.semantic.protocol_identity
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.FORCE_WEIGHT_SYSTEM_MISMATCH,),
            (
                "SYSTEM_WEIGHT from the exact total-force signal, artifact, identity, "
                "context, and protocol",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if weight.observation.result.quality.flags != weight.qc.quality_flags:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("SYSTEM_WEIGHT quality flags linked to its baseline QC",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    recomputed = estimate_system_weight(force_input, weight.segment)
    if not isinstance(recomputed, SystemWeightResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("source-recomputed SYSTEM_WEIGHT baseline statistics",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    actual_qc = weight.qc
    expected_qc = recomputed.qc
    if (
        weight.value_n != recomputed.value_n
        or actual_qc.sample_count != expected_qc.sample_count
        or actual_qc.elapsed_sample_span_s != expected_qc.elapsed_sample_span_s
        or actual_qc.mean_force_n != expected_qc.mean_force_n
        or actual_qc.standard_deviation_n != expected_qc.standard_deviation_n
        or actual_qc.range_n != expected_qc.range_n
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("SYSTEM_WEIGHT value and QC recomputed from the exact source segment",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _validate_interval(
    interval: CMJIntegrationInterval | None,
    series: CMJMechanicsSeries,
    claim: str,
    *,
    require_nonzero: bool,
) -> RefusalResult | None:
    if interval is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("explicit CMJIntegrationInterval",),
            series.source_observation_ids,
        )
    accepted_source_ids = (series.series_id, *series.source_signal_ids)
    if interval.source_signal_id not in accepted_source_ids:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("interval source signal linked to the exact source series",),
            series.source_observation_ids,
        )
    if (
        interval.end_index >= series.source_sample_count
        or interval.start_index < series.sample_start_index
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("interval boundaries inside source sample support",),
            series.source_observation_ids,
        )
    if require_nonzero and interval.end_index <= interval.start_index:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("at least two endpoint samples for a scalar integral",),
            series.source_observation_ids,
        )
    if interval.kind is CMJIntegrationIntervalKind.EVENT_BOUNDED_INTERVAL:
        if not interval.event_ids:
            return _mechanics_refusal(
                claim,
                (RefusalReasonCode.EVENT_BOUNDARY_MISMATCH,),
                ("event occurrence references for event-bounded integration",),
                series.source_observation_ids,
            )
        if any(
            event.source_signal_id not in accepted_source_ids
            for event in (interval.start_event, interval.end_event)
            if event
        ):
            return _mechanics_refusal(
                claim,
                (RefusalReasonCode.EVENT_BOUNDARY_MISMATCH,),
                ("event occurrence source signal linked to the integration series",),
                series.source_observation_ids,
            )
    return None


def _trapezoid_integral(
    series: CMJMechanicsSeries,
    start_index: int,
    end_index: int,
) -> float:
    total = 0.0
    for source_index in range(start_index + 1, end_index + 1):
        left = series.samples[source_index - 1 - series.sample_start_index]
        right = series.samples[source_index - series.sample_start_index]
        total += (
            0.5 * (left + right) * _sample_delta(series.timebase, source_index - 1, source_index)
        )
    return total


def _cumulative_integral(
    series: CMJMechanicsSeries,
    start_index: int,
    end_index: int,
    initial_value: float,
) -> tuple[float, ...]:
    values = [initial_value]
    current = initial_value
    for source_index in range(start_index + 1, end_index + 1):
        left = series.samples[source_index - 1 - series.sample_start_index]
        right = series.samples[source_index - series.sample_start_index]
        current += (
            0.5 * (left + right) * _sample_delta(series.timebase, source_index - 1, source_index)
        )
        values.append(current)
    return tuple(values)


def _processing_parameters(
    *,
    operation: RegistryReference,
    system_contract: CMJMechanicalSystemContract,
    source_signal_ids: tuple[InstanceIdentifier, ...],
    source_observation_ids: tuple[InstanceIdentifier, ...],
    source_identity_ids: tuple[ScientificIdentifier, ...],
    unit: UnitReference,
    axis: RegistryReference,
    frame: RegistryReference,
    sign: SignConvention,
    interval: CMJIntegrationInterval | None = None,
    initial_condition: QualifiedZeroVelocityReference | InitialVelocityCondition | None = None,
    origin: DisplacementOrigin | None = None,
    extra: tuple[MetadataEntry, ...] = (),
) -> tuple[MetadataEntry, ...]:
    entries = [
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("operation_version", operation.identifier.version),
        MetadataEntry("system_contract", canonical_json(system_contract)),
        MetadataEntry("source_signal_ids", canonical_json(source_signal_ids)),
        MetadataEntry("source_observation_ids", canonical_json(source_observation_ids)),
        MetadataEntry("source_measurement_identity_ids", canonical_json(source_identity_ids)),
        MetadataEntry("output_unit", unit.identifier.stable_id),
        MetadataEntry("physical_axis", axis.stable_id),
        MetadataEntry("reference_frame", frame.stable_id),
        MetadataEntry("sign_convention", canonical_json(sign)),
        MetadataEntry("filtering", "none"),
        MetadataEntry("interpolation", "none"),
        MetadataEntry("resampling", "none"),
        MetadataEntry("drift_correction", "none"),
        MetadataEntry("endpoint_constraint", "none"),
        MetadataEntry("uncertainty_propagation", "not_assessed"),
    ]
    if interval is not None:
        entries.append(MetadataEntry("integration_interval", canonical_json(interval)))
        entries.append(MetadataEntry("integration_boundary", interval.interval_semantics))
        entries.append(MetadataEntry("integration_method", interval.integration_method.stable_id))
    if initial_condition is not None:
        entries.append(MetadataEntry("zero_velocity_reference", canonical_json(initial_condition)))
    if origin is not None:
        entries.append(MetadataEntry("displacement_origin", canonical_json(origin)))
    entries.extend(extra)
    return tuple(entries)


def _upstream_processing_semantics(
    observation: ScientificMeasurementObservation,
    *,
    prefix: str,
) -> tuple[MetadataEntry, ...]:
    """Carry method semantics forward without making trial instance IDs comparable."""

    identity = _cmj_observation_identity(observation)
    ignored_keys = {
        "source_signal_id",
        "source_signal_ids",
        "source_artifact_id",
        "source_artifact_ids",
        "source_observation_id",
        "source_observation_ids",
        "source_measurement_identity_id",
        "source_measurement_identity_ids",
        "source_net_force_observation_id",
        "source_net_force_series_id",
        "source_system_weight_observation_id",
        "physical_mass_observation_id",
        "source_acceleration_observation_id",
        "source_acceleration_series_id",
        "source_velocity_observation_id",
        "source_velocity_series_id",
        "source_event_ids",
        "integration_interval",
        "initial_velocity_condition",
        "zero_velocity_reference",
        "displacement_origin",
    }
    return tuple(
        MetadataEntry(f"{prefix}{entry.key}", entry.value)
        for entry in identity.processing.method_parameters
        if entry.key not in ignored_keys
    )


def _series_output(
    *,
    source_identity: CMJMeasurementIdentity,
    source_context: ObservationContext,
    source_observations: tuple[ScientificMeasurementObservation, ...],
    source_signal_ids: tuple[InstanceIdentifier, ...],
    quantity: CMJMechanicsQuantity,
    samples: tuple[float, ...],
    source_sample_count: int,
    sample_start_index: int,
    timebase: SignalTimebase,
    unit: UnitReference,
    axis: RegistryReference,
    frame: RegistryReference,
    sign: SignConvention,
    system_contract: CMJMechanicalSystemContract,
    integration_interval: CMJIntegrationInterval | None,
    initial_velocity_condition: QualifiedZeroVelocityReference | None,
    displacement_origin: DisplacementOrigin | None,
    extra_parameters: tuple[MetadataEntry, ...],
    evidence: RegistryReference,
    additional_source_observation_ids: tuple[InstanceIdentifier, ...] = (),
    additional_source_identity_ids: tuple[ScientificIdentifier, ...] = (),
    output_entity_id: InstanceIdentifier | None = None,
) -> tuple[CMJMechanicsSeries, ScientificMeasurementObservation]:
    operation, schema, metric, expected_unit = _expected_quantity_metadata(quantity)
    if unit.identifier.stable_id != expected_unit.identifier.stable_id:
        raise ValueError("series unit does not match quantity")
    events = _event_values(integration_interval, initial_velocity_condition, displacement_origin)
    all_observations = source_observations
    base = _merge_sources(all_observations, events)
    observation_ids = _unique(
        (
            *_obs_ids(all_observations),
            *additional_source_observation_ids,
            *_event_observation_ids(events),
        )
    )
    source_signal_ids = _unique(source_signal_ids)
    entity_ids = _unique(
        (*observation_ids, *source_signal_ids, *(event.occurrence_id for event in events))
    )
    source_identity_ids = _unique(
        (
            *tuple(observation.identity.identity_id for observation in all_observations),
            *additional_source_identity_ids,
            *_event_identity_ids(events),
        )
    )
    source_artifact_ids = tuple(
        sorted((item.artifact_id for item in base.source_artifacts), key=_id)
    )
    source_acquisition_ids = tuple(
        sorted((item.acquisition_id for item in base.acquisitions), key=_id)
    )
    parameters = _processing_parameters(
        operation=operation,
        system_contract=system_contract,
        source_signal_ids=source_signal_ids,
        source_observation_ids=observation_ids,
        source_identity_ids=source_identity_ids,
        unit=unit,
        axis=axis,
        frame=frame,
        sign=sign,
        interval=integration_interval,
        initial_condition=initial_velocity_condition,
        origin=displacement_origin,
        extra=extra_parameters,
    )
    digest = canonical_hash(
        {
            "operation": operation.stable_id,
            "quantity": quantity,
            "source_observations": observation_ids,
            "source_signals": source_signal_ids,
            "source_identities": source_identity_ids,
            "parameters": parameters,
            "samples": samples,
            "source_sample_count": source_sample_count,
            "sample_start_index": sample_start_index,
            "timebase": timebase,
            "unit": unit,
            "system_contract": system_contract,
            "output_entity_id": output_entity_id,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_entity_id or InstanceIdentifier(
        "observation", f"cmj-{quantity.value.lower()}:{digest}"
    )
    if observation_id.instance_type != "observation":
        raise ValueError("output_entity_id must identify an observation")
    series_id = InstanceIdentifier("signal", f"cmj-{quantity.value.lower()}:{digest}")
    artifact_id = InstanceIdentifier("artifact", f"cmj-{quantity.value.lower()}:{digest}")
    processing_run_id = InstanceIdentifier(
        "processing-run", f"cmj-{quantity.value.lower()}:{digest}"
    )
    identity_id = ScientificIdentifier(
        "dynamislm",
        "measurement-identity",
        f"cmj-{quantity.value.lower()}-{digest}",
        CMJ_REGISTRY_VERSION,
    )
    processing = ProcessingIdentity(
        registered_operation=operation,
        method_parameters=parameters,
        integration_method=(
            CMJ_TRAPEZOIDAL_INTEGRATION_METHOD if integration_interval is not None else None
        ),
        unit=unit,
        sign_convention=sign,
    )
    identity = _derived_identity(
        source_identity,
        identity_id=identity_id,
        measurand=_expected_measurand(quantity),
        metric=metric,
        processing=processing,
        processing_method=operation,
        software_version=RES37_SOFTWARE_VERSION,
    )
    content_digest = canonical_hash(
        {
            "quantity": quantity,
            "samples": samples,
            "timebase": timebase,
            "source_sample_count": source_sample_count,
            "sample_start_index": sample_start_index,
            "unit": unit,
            "axis": axis,
            "frame": frame,
            "sign": sign,
            "operation": operation,
            "system_contract": system_contract,
        }
    )
    output_artifact = SourceArtifact(
        artifact_id=artifact_id,
        content_digest=content_digest,
        media_type="application/vnd.dynamislm.cmj.mechanics-series",
        immutable=True,
    )
    processing_run = ProcessingRun(
        processing_run_id=processing_run_id,
        source_artifact_ids=source_artifact_ids,
        method=operation,
        parameters=parameters,
        software_version=RES37_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=processing_run,
        output_entity_id=observation_id,
        source_observation_ids=observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        output_artifacts=(output_artifact,),
        produced_artifact_ids=(artifact_id,),
        supported_by=(evidence, CMJ_MECHANICS_SYSTEM_CONTRACT),
        evidence_references=(
            EvidenceReference(evidence, "registered mechanics authority for this output"),
        ),
        recorded_at=source_context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=source_context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"cmj-{quantity.value.lower()}:{digest}"),
            value=StructuredOutputReference(artifact_id=artifact_id, schema=schema),
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
    series = CMJMechanicsSeries(
        series_id=series_id,
        quantity=quantity,
        artifact_id=artifact_id,
        schema=schema,
        source_signal_ids=source_signal_ids,
        source_observation_ids=observation_ids,
        source_entity_ids=entity_ids,
        source_artifact_ids=source_artifact_ids,
        source_measurement_identity_ids=source_identity_ids,
        processing_run_id=processing_run_id,
        source_sample_count=source_sample_count,
        sample_start_index=sample_start_index,
        samples=samples,
        timebase=timebase,
        unit=unit,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
        operation=operation,
        system_contract=system_contract,
        integration_method=(CMJ_TRAPEZOIDAL_INTEGRATION_METHOD if integration_interval else None),
        integration_interval=integration_interval,
        initial_velocity_condition=initial_velocity_condition,
        displacement_origin=displacement_origin,
        source_event_ids=tuple(event.occurrence_id for event in events),
    )
    return series, observation


def _scalar_output(
    *,
    source_identity: CMJMeasurementIdentity,
    source_context: ObservationContext,
    source_observations: tuple[ScientificMeasurementObservation, ...],
    source_signal_ids: tuple[InstanceIdentifier, ...],
    value: float,
    unit: UnitReference,
    operation: RegistryReference,
    measurand: RegistryReference,
    metric: RegistryReference,
    interval: CMJIntegrationInterval,
    timebase: SignalTimebase,
    system_contract: CMJMechanicalSystemContract,
    extra_parameters: tuple[MetadataEntry, ...],
    additional_source_observation_ids: tuple[InstanceIdentifier, ...] = (),
    additional_source_identity_ids: tuple[ScientificIdentifier, ...] = (),
) -> ScientificMeasurementObservation:
    events = _event_values(interval)
    base = _merge_sources(source_observations, events)
    observation_ids = _unique(
        (
            *_obs_ids(source_observations),
            *additional_source_observation_ids,
            *_event_observation_ids(events),
        )
    )
    source_signal_ids = _unique(source_signal_ids)
    source_identity_ids = _unique(
        (
            *tuple(observation.identity.identity_id for observation in source_observations),
            *additional_source_identity_ids,
            *_event_identity_ids(events),
        )
    )
    source_artifact_ids = tuple(
        sorted((item.artifact_id for item in base.source_artifacts), key=_id)
    )
    source_acquisition_ids = tuple(
        sorted((item.acquisition_id for item in base.acquisitions), key=_id)
    )
    source_axis = source_identity.acquisition.physical_axis
    source_frame = source_identity.acquisition.reference_frame
    source_sign = source_identity.acquisition.sign_convention
    if source_axis is None or source_frame is None or source_sign is None:
        raise ValueError("scalar mechanics source semantics must be explicit")
    parameters = _processing_parameters(
        operation=operation,
        system_contract=system_contract,
        source_signal_ids=source_signal_ids,
        source_observation_ids=observation_ids,
        source_identity_ids=source_identity_ids,
        unit=unit,
        axis=source_axis,
        frame=source_frame,
        sign=source_sign,
        interval=interval,
        extra=(MetadataEntry("source_timebase", canonical_json(timebase)), *extra_parameters),
    )
    digest = canonical_hash(
        {
            "operation": operation,
            "value": value,
            "unit": unit,
            "parameters": parameters,
            "source_observations": observation_ids,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = InstanceIdentifier("observation", f"cmj-net-vertical-impulse:{digest}")
    identity = _derived_identity(
        source_identity,
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"cmj-net-vertical-impulse-{digest}",
            CMJ_REGISTRY_VERSION,
        ),
        measurand=measurand,
        metric=metric,
        processing=ProcessingIdentity(
            registered_operation=operation,
            method_parameters=parameters,
            integration_method=CMJ_TRAPEZOIDAL_INTEGRATION_METHOD,
            unit=unit,
            sign_convention=source_sign,
        ),
        processing_method=operation,
        software_version=RES37_SOFTWARE_VERSION,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"cmj-net-vertical-impulse:{digest}"
        ),
        source_artifact_ids=source_artifact_ids,
        method=operation,
        parameters=parameters,
        software_version=RES37_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        supported_by=(RES37_DECISION_IMPULSE_INTEGRATION, CMJ_MECHANICS_SYSTEM_CONTRACT),
        evidence_references=(
            EvidenceReference(RES37_DECISION_IMPULSE_INTEGRATION, "registered scalar integral"),
        ),
        recorded_at=source_context.observed_at,
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=source_context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"cmj-net-vertical-impulse:{digest}"),
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


def _force_semantics(
    force_input: CMJForceInput,
    claim: str,
) -> tuple[RegistryReference, RegistryReference, SignConvention] | RefusalResult:
    axis = force_input.signal.physical_axis
    frame = force_input.signal.reference_frame
    sign = force_input.signal.sign_convention
    if axis is None or frame is None or sign is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("vertical axis, reference frame, and upward-positive sign",),
            (force_input.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return axis, frame, sign


def derive_net_vertical_force(
    force: TotalSupportedForceResult | CMJForceInput,
    system_weight: SystemWeightResult | None = None,
    system_contract: CMJMechanicalSystemContract | None = None,
    *,
    counterpart: CMJForceInput | None = None,
) -> NetVerticalForceResult | RefusalResult:
    """Derive ``F_net,z = Fz - SYSTEM_WEIGHT`` without requiring mass."""

    claim = "derive supported-system net vertical force"
    total, total_refusal = _resolve_total_force(force, counterpart, claim)
    if total_refusal is not None:
        return total_refusal
    if total is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("RES-35 total supported force",),
        )
    force_input, force_refusal = _force_refusal(total, claim)
    if force_refusal is not None:
        return force_refusal
    if force_input is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("validated total supported force input",),
        )
    contract_refusal = _validate_contract(
        system_contract,
        claim,
        (force_input.observation.observation_id,),
        protocol=force_input.identity.semantic.protocol_identity,
    )
    if contract_refusal is not None:
        return contract_refusal
    weight_refusal = _weight_refusal(force_input, system_weight, claim)
    if weight_refusal is not None:
        return weight_refusal
    if system_weight is None or system_contract is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SYSTEM_WEIGHT_REQUIRED,),
            ("validated SYSTEM_WEIGHT and mechanics contract",),
            (force_input.observation.observation_id,),
        )
    weight_identity = system_weight.observation.identity
    if not isinstance(weight_identity, CMJMeasurementIdentity):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.FORCE_WEIGHT_SYSTEM_MISMATCH,),
            ("CMJ SYSTEM_WEIGHT identity",),
            (force_input.observation.observation_id, system_weight.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    semantics = _force_semantics(force_input, claim)
    if isinstance(semantics, RefusalResult):
        return semantics
    axis, frame, sign = semantics
    timebase = force_input.signal.timebase
    if timebase is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.TIMEBASE_INSUFFICIENT,),
            ("registered total supported force timebase",),
            (force_input.observation.observation_id,),
        )
    samples = tuple(sample - system_weight.value_n for sample in force_input.signal.samples)
    source_operation = force_input.identity.processing.registered_operation
    weight_operation = weight_identity.processing.registered_operation
    weight_estimator = weight_identity.processing.estimator
    protocol_identity = force_input.identity.semantic.protocol_identity
    protocol_loading = (
        protocol_identity.external_loading.value
        if protocol_identity is not None and protocol_identity.external_loading is not None
        else None
    )
    extra = (
        MetadataEntry(
            "source_force_processing_operation",
            source_operation.stable_id if source_operation is not None else "unresolved",
        ),
        MetadataEntry(
            "source_system_weight_observation_id",
            system_weight.observation.observation_id.qualified,
        ),
        MetadataEntry("system_boundary", "SUPPORTED_PHYSICAL_SYSTEM"),
        MetadataEntry("external_force_model", system_contract.external_force_model.stable_id),
        MetadataEntry(
            "protocol_external_loading",
            protocol_loading if isinstance(protocol_loading, str) else "unresolved",
        ),
        MetadataEntry(
            "system_weight_operation",
            weight_operation.stable_id if weight_operation is not None else "unresolved",
        ),
        MetadataEntry(
            "system_weight_estimator",
            weight_estimator.stable_id if weight_estimator is not None else "unresolved",
        ),
        MetadataEntry(
            "system_weight_selection_method", system_weight.segment.selection_method.stable_id
        ),
        MetadataEntry(
            "system_weight_segment",
            canonical_json(system_weight.segment),
        ),
        MetadataEntry("system_weight_qc", canonical_json(system_weight.qc)),
        MetadataEntry(
            "system_weight_quality_flags",
            canonical_json(system_weight.observation.result.quality.flags),
        ),
        MetadataEntry("system_weight_start_index", system_weight.segment.start_index),
        MetadataEntry("system_weight_end_index", system_weight.segment.end_index),
    )
    series, observation = _series_output(
        source_identity=force_input.identity,
        source_context=force_input.observation.context,
        source_observations=(force_input.observation, system_weight.observation),
        source_signal_ids=(force_input.signal.signal_id,),
        quantity=CMJMechanicsQuantity.NET_VERTICAL_FORCE,
        samples=samples,
        source_sample_count=len(force_input.signal.samples),
        sample_start_index=0,
        timebase=timebase,
        unit=NEWTON,
        axis=axis,
        frame=frame,
        sign=sign,
        system_contract=system_contract,
        integration_interval=None,
        initial_velocity_condition=None,
        displacement_origin=None,
        extra_parameters=extra,
        evidence=RES37_DECISION_SUPPORTED_SYSTEM_NET_FORCE,
    )
    return NetVerticalForceResult(
        observation=observation,
        series=series,
        source_system_weight_observation_id=system_weight.observation.observation_id,
    )


def integrate_net_vertical_impulse(
    net_force: NetVerticalForceResult,
    interval: CMJIntegrationInterval | None = None,
) -> NetVerticalImpulseResult | RefusalResult:
    """Integrate net force over an explicit inclusive interval to N·s."""

    claim = "integrate scalar net vertical impulse"
    if not isinstance(net_force, NetVerticalForceResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("NetVerticalForceResult",),
        )
    interval_refusal = _validate_interval(interval, net_force.series, claim, require_nonzero=True)
    if interval_refusal is not None:
        return interval_refusal
    if interval is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("explicit integration interval",),
            net_force.series.source_observation_ids,
        )
    value = _trapezoid_integral(net_force.series, interval.start_index, interval.end_index)
    operation_parameters = (
        MetadataEntry(
            "source_net_force_observation_id", net_force.observation.observation_id.qualified
        ),
        MetadataEntry("source_net_force_series_id", net_force.series.series_id.qualified),
        MetadataEntry(
            "source_system_weight_observation_id",
            net_force.source_system_weight_observation_id.qualified,
        ),
        *_upstream_processing_semantics(
            net_force.observation,
            prefix="source_net_force_",
        ),
    )
    observation = _scalar_output(
        source_identity=_cmj_observation_identity(net_force.observation),
        source_context=net_force.observation.context,
        source_observations=(net_force.observation,),
        source_signal_ids=(net_force.series.series_id, *net_force.series.source_signal_ids),
        value=value,
        unit=NEWTON_SECOND,
        operation=CMJ_NET_VERTICAL_IMPULSE_OPERATION,
        measurand=CMJ_NET_VERTICAL_IMPULSE_MEASURAND,
        metric=CMJ_NET_VERTICAL_IMPULSE_METRIC,
        interval=interval,
        timebase=net_force.series.timebase,
        system_contract=net_force.system_contract,
        extra_parameters=operation_parameters,
        additional_source_observation_ids=net_force.series.source_observation_ids,
        additional_source_identity_ids=net_force.series.source_measurement_identity_ids,
    )
    return NetVerticalImpulseResult(
        observation=observation,
        interval=interval,
        source_net_force_series_id=net_force.series.series_id,
        source_system_weight_observation_id=net_force.source_system_weight_observation_id,
        system_contract=net_force.system_contract,
        timebase=net_force.series.timebase,
    )


def derive_supported_system_com_acceleration(
    net_force: NetVerticalForceResult,
    physical_system_mass: PhysicalSystemMassResult
    | StandardGravityMassEquivalentResult
    | None = None,
    system_contract: CMJMechanicalSystemContract | None = None,
) -> SupportedSystemComAccelerationResult | RefusalResult:
    """Derive supported-system COM acceleration using RES-44 physical mass only."""

    claim = "derive supported-system COM vertical acceleration"
    if not isinstance(net_force, NetVerticalForceResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("NetVerticalForceResult",),
        )
    source_ids: tuple[InstanceIdentifier, ...] = (net_force.observation.observation_id,)
    net_identity = net_force.observation.identity
    protocol = (
        net_identity.semantic.protocol_identity
        if isinstance(net_identity, CMJMeasurementIdentity)
        else None
    )
    contract_refusal = _validate_contract(
        system_contract,
        claim,
        source_ids,
        protocol=protocol,
    )
    if contract_refusal is not None:
        return contract_refusal
    if system_contract is None or system_contract != net_force.system_contract:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED,),
            ("the acceleration contract must equal the net-force system contract",),
            source_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if physical_system_mass is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.PHYSICAL_SYSTEM_MASS_REQUIRED,),
            ("RES-44 PhysicalSystemMassResult from applicable local gravity",),
            source_ids,
        )
    if isinstance(physical_system_mass, StandardGravityMassEquivalentResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.STANDARD_GRAVITY_EQUIVALENT_NOT_AUTHORIZED,),
            ("PhysicalSystemMassResult; standard-gravity equivalent is not physical mass",),
            (*source_ids, physical_system_mass.observation.observation_id),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if not isinstance(physical_system_mass, PhysicalSystemMassResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.PHYSICAL_SYSTEM_MASS_REQUIRED,),
            ("typed PhysicalSystemMassResult",),
            source_ids,
        )
    source_ids = (*source_ids, physical_system_mass.observation.observation_id)
    if (
        physical_system_mass.source_system_weight_observation_id
        != net_force.source_system_weight_observation_id
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.MASS_SOURCE_MISMATCH,),
            ("physical mass derived from the exact SYSTEM_WEIGHT used by net force",),
            source_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    mass_identity = physical_system_mass.observation.identity
    if (
        physical_system_mass.observation.context != net_force.observation.context
        or not isinstance(mass_identity, CMJMeasurementIdentity)
        or mass_identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id
        or mass_identity.semantic.protocol_identity != protocol
        or physical_system_mass.observation.result.unit is None
        or physical_system_mass.observation.result.unit.identifier.stable_id
        != KILOGRAM.identifier.stable_id
        or not math.isfinite(physical_system_mass.value_kg)
        or physical_system_mass.value_kg <= 0
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.MASS_SOURCE_MISMATCH,),
            ("finite positive kg mass with exact supported-system context and identity",),
            source_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if system_contract is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED,),
            ("explicit supported-system mechanics contract",),
            source_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    axis = net_force.series.physical_axis
    frame = net_force.series.reference_frame
    sign = net_force.series.sign_convention
    extra = (
        MetadataEntry(
            "source_net_force_processing_operation",
            net_force.series.operation.stable_id,
        ),
        MetadataEntry(
            "physical_mass_observation_id",
            physical_system_mass.observation.observation_id.qualified,
        ),
        MetadataEntry(
            "source_system_weight_observation_id",
            net_force.source_system_weight_observation_id.qualified,
        ),
        MetadataEntry("gravity_reference", canonical_json(physical_system_mass.gravity_reference)),
        MetadataEntry(
            "physical_mass_operation",
            CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT.stable_id,
        ),
        *_upstream_processing_semantics(
            net_force.observation,
            prefix="source_net_force_",
        ),
    )
    series, observation = _series_output(
        source_identity=_cmj_observation_identity(net_force.observation),
        source_context=net_force.observation.context,
        source_observations=(net_force.observation, physical_system_mass.observation),
        source_signal_ids=(net_force.series.series_id, *net_force.series.source_signal_ids),
        quantity=CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION,
        samples=tuple(value / physical_system_mass.value_kg for value in net_force.samples),
        source_sample_count=net_force.series.source_sample_count,
        sample_start_index=net_force.series.sample_start_index,
        timebase=net_force.series.timebase,
        unit=METERS_PER_SECOND_SQUARED,
        axis=axis,
        frame=frame,
        sign=sign,
        system_contract=system_contract,
        integration_interval=None,
        initial_velocity_condition=None,
        displacement_origin=None,
        extra_parameters=extra,
        evidence=RES37_DECISION_PHYSICAL_MASS_ACCELERATION,
        additional_source_observation_ids=net_force.series.source_observation_ids,
        additional_source_identity_ids=net_force.series.source_measurement_identity_ids,
    )
    return SupportedSystemComAccelerationResult(
        observation=observation,
        series=series,
        source_physical_system_mass_observation_id=physical_system_mass.observation.observation_id,
        source_system_weight_observation_id=net_force.source_system_weight_observation_id,
    )


def _qualified_zero_velocity_reference_refusal(
    acceleration: SupportedSystemComAccelerationResult,
    interval: CMJIntegrationInterval,
    reference: object,
    claim: str,
) -> RefusalResult | None:
    observation_ids = acceleration.series.source_observation_ids
    if not isinstance(reference, QualifiedZeroVelocityReference):
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            (
                "QualifiedZeroVelocityReference derived from the exact compatible "
                "RES-35 SystemWeightResult",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not reference.is_authorized:
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            (
                "explicit RES-35 weighing-baseline acceptability adjudication for the "
                "qualified zero-velocity reference",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    observation_ids = _unique((*observation_ids, reference.source_system_weight_observation_id))
    acceleration_parameters = {
        entry.key: entry.value
        for entry in acceleration.observation.identity.processing.method_parameters
    }
    if (
        reference.source_system_weight_observation_id
        != acceleration.source_system_weight_observation_id
        or reference.source_system_weight_observation_id
        not in acceleration.series.source_observation_ids
        or reference.source_signal_id not in acceleration.series.source_signal_ids
        or reference.source_artifact_id not in acceleration.series.source_artifact_ids
        or reference.source_measurement_identity_id
        not in acceleration.series.source_measurement_identity_ids
        or reference.weighing_segment.end_index > acceleration.series.source_sample_count
        or acceleration_parameters.get("source_net_force_system_weight_segment")
        != canonical_json(reference.weighing_segment)
        or acceleration_parameters.get("source_net_force_system_weight_qc")
        != canonical_json(reference.weighing_qc)
        or acceleration_parameters.get("source_net_force_system_weight_quality_flags")
        != canonical_json(reference.weighing_qc.quality_flags)
    ):
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_SOURCE_MISMATCH,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            (
                "qualified reference from the exact source signal, artifact, measurement "
                "identity, trial/context, and SYSTEM_WEIGHT observation",
            ),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if interval.source_signal_id not in (
        acceleration.series.series_id,
        reference.source_signal_id,
    ):
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_SOURCE_MISMATCH,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            ("integration interval source linked to the qualified reference source",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if reference.sample_index != interval.start_index:
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            ("qualified zero-velocity sample equal to the inclusive integration start",),
            observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def derive_supported_system_com_velocity(
    acceleration: SupportedSystemComAccelerationResult,
    interval: CMJIntegrationInterval | None = None,
    initial_velocity_condition: QualifiedZeroVelocityReference
    | InitialVelocityCondition
    | None = None,
) -> SupportedSystemComVelocityResult | RefusalResult:
    """Integrate acceleration from an exact qualified zero-velocity reference."""

    claim = "derive supported-system COM vertical velocity"
    if not isinstance(acceleration, SupportedSystemComAccelerationResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("SupportedSystemComAccelerationResult",),
        )
    interval_refusal = _validate_interval(
        interval, acceleration.series, claim, require_nonzero=False
    )
    if interval_refusal is not None:
        return interval_refusal
    if interval is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.INTEGRATION_INTERVAL_INVALID,),
            ("explicit velocity integration interval",),
            acceleration.series.source_observation_ids,
        )
    if initial_velocity_condition is None:
        return _mechanics_refusal(
            claim,
            (
                RefusalReasonCode.ZERO_VELOCITY_REFERENCE_REQUIRED,
                RefusalReasonCode.INITIAL_CONDITION_UNRESOLVED,
            ),
            ("explicit QualifiedZeroVelocityReference",),
            acceleration.series.source_observation_ids,
        )
    reference_refusal = _qualified_zero_velocity_reference_refusal(
        acceleration,
        interval,
        initial_velocity_condition,
        claim,
    )
    if reference_refusal is not None:
        return reference_refusal
    if not isinstance(initial_velocity_condition, QualifiedZeroVelocityReference):
        raise AssertionError("validated velocity reference must be qualified")
    values = _cumulative_integral(
        acceleration.series,
        interval.start_index,
        interval.end_index,
        initial_velocity_condition.value_m_per_s,
    )
    axis = acceleration.series.physical_axis
    frame = acceleration.series.reference_frame
    sign = acceleration.series.sign_convention
    extra = (
        MetadataEntry(
            "source_acceleration_observation_id", acceleration.observation.observation_id.qualified
        ),
        MetadataEntry("source_acceleration_series_id", acceleration.series.series_id.qualified),
        *_upstream_processing_semantics(
            acceleration.observation,
            prefix="source_acceleration_",
        ),
    )
    series, observation = _series_output(
        source_identity=_cmj_observation_identity(acceleration.observation),
        source_context=acceleration.observation.context,
        source_observations=(acceleration.observation,),
        source_signal_ids=(acceleration.series.series_id, *acceleration.series.source_signal_ids),
        quantity=CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
        samples=values,
        source_sample_count=acceleration.series.source_sample_count,
        sample_start_index=interval.start_index,
        timebase=acceleration.series.timebase,
        unit=METERS_PER_SECOND,
        axis=axis,
        frame=frame,
        sign=sign,
        system_contract=acceleration.system_contract,
        integration_interval=interval,
        initial_velocity_condition=initial_velocity_condition,
        displacement_origin=None,
        extra_parameters=extra,
        evidence=RES46_DECISION_QUALIFIED_ZERO_VELOCITY,
        additional_source_observation_ids=acceleration.series.source_observation_ids,
        additional_source_identity_ids=acceleration.series.source_measurement_identity_ids,
    )
    return SupportedSystemComVelocityResult(
        observation=observation,
        series=series,
        initial_velocity_condition=initial_velocity_condition,
    )


def derive_supported_system_com_relative_vertical_displacement(
    velocity: SupportedSystemComVelocityResult,
    origin: DisplacementOrigin | None = None,
) -> SupportedSystemComRelativeDisplacementResult | RefusalResult:
    """Integrate velocity from an explicit relative-coordinate origin."""

    claim = "derive supported-system COM relative vertical displacement"
    if not isinstance(velocity, SupportedSystemComVelocityResult):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("SupportedSystemComVelocityResult",),
        )
    if origin is None:
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.DISPLACEMENT_REFERENCE_UNRESOLVED,),
            ("explicit relative displacement origin",),
            velocity.series.source_observation_ids,
        )
    if (
        origin.source_velocity_series_id != velocity.series.series_id
        or origin.sample_index != velocity.series.sample_start_index
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.DISPLACEMENT_REFERENCE_UNRESOLVED,),
            ("zero origin attached to the exact velocity series start sample",),
            velocity.series.source_observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if origin.reference_event is not None and (
        origin.reference_event.source_signal_id not in velocity.series.source_signal_ids
        or origin.reference_event.sample_index != origin.sample_index
    ):
        return _mechanics_refusal(
            claim,
            (RefusalReasonCode.EVENT_BOUNDARY_MISMATCH,),
            ("displacement origin event linked to the exact velocity source",),
            velocity.series.source_observation_ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    start = velocity.series.sample_start_index
    end = start + len(velocity.series.samples) - 1
    values = _cumulative_integral(velocity.series, start, end, origin.value_m)
    extra = (
        MetadataEntry(
            "source_velocity_observation_id", velocity.observation.observation_id.qualified
        ),
        MetadataEntry("source_velocity_series_id", velocity.series.series_id.qualified),
        MetadataEntry("coordinate_reference", origin.coordinate_reference),
        MetadataEntry(
            "source_velocity_initial_condition_semantics",
            canonical_json(_condition_key(velocity.initial_velocity_condition)),
        ),
        *_upstream_processing_semantics(
            velocity.observation,
            prefix="source_velocity_",
        ),
    )
    series, observation = _series_output(
        source_identity=_cmj_observation_identity(velocity.observation),
        source_context=velocity.observation.context,
        source_observations=(velocity.observation,),
        source_signal_ids=(velocity.series.series_id, *velocity.series.source_signal_ids),
        quantity=CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
        samples=values,
        source_sample_count=velocity.series.source_sample_count,
        sample_start_index=start,
        timebase=velocity.series.timebase,
        unit=METER,
        axis=velocity.series.physical_axis,
        frame=velocity.series.reference_frame,
        sign=velocity.series.sign_convention,
        system_contract=velocity.system_contract,
        integration_interval=velocity.series.integration_interval,
        initial_velocity_condition=velocity.initial_velocity_condition,
        displacement_origin=origin,
        extra_parameters=extra,
        evidence=RES37_DECISION_DISPLACEMENT_REFERENCE,
        additional_source_observation_ids=velocity.series.source_observation_ids,
        additional_source_identity_ids=velocity.series.source_measurement_identity_ids,
    )
    return SupportedSystemComRelativeDisplacementResult(
        observation=observation,
        series=series,
        displacement_origin=origin,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJMechanicsComparabilityRequest:
    """Claim-relative request retaining the mechanics method and interval identities."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    left_identity: CMJMeasurementIdentity
    right_identity: CMJMeasurementIdentity
    left_series: CMJMechanicsSeries | None
    right_series: CMJMechanicsSeries | None
    left_interval: CMJIntegrationInterval | None
    right_interval: CMJIntegrationInterval | None
    claim: str

    def __post_init__(self) -> None:
        _text(self.claim, "claim")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("mechanics comparability requires two distinct observations")


def _event_key(event: CMJEventOccurrence | None) -> object:
    if event is None:
        return None
    return (
        event.definition.reference.stable_id,
        event.detector_method.reference.stable_id,
        event.detector_parameters,
        event.source_sample_count,
        event.sample_index,
        event.source_timebase,
        event.effective_threshold_n,
    )


def _interval_key(interval: CMJIntegrationInterval | None) -> object:
    if interval is None:
        return None
    return (
        interval.kind,
        interval.start_index,
        interval.end_index,
        interval.boundary_convention.stable_id,
        interval.integration_method.stable_id,
        _event_key(interval.start_event),
        _event_key(interval.end_event),
    )


def _condition_key(
    condition: QualifiedZeroVelocityReference | InitialVelocityCondition | None,
) -> object:
    if condition is None:
        return None
    if isinstance(condition, QualifiedZeroVelocityReference):
        segment = condition.weighing_segment
        return (
            condition.method.stable_id,
            condition.evidence_decision.stable_id,
            condition.sample_index,
            condition.value_m_per_s,
            condition.unit.identifier.stable_id,
            segment.selection_method.stable_id,
            segment.start_index,
            segment.end_index,
            tuple((entry.key, entry.value) for entry in segment.selection_parameters),
            canonical_json(condition.weighing_qc),
        )
    return (
        condition.method.stable_id,
        condition.sample_index,
        condition.value_m_per_s,
        condition.unit.identifier.stable_id,
        condition.assumption,
        _event_key(condition.reference_event),
    )


def _origin_key(origin: DisplacementOrigin | None) -> object:
    if origin is None:
        return None
    return (
        origin.method.stable_id,
        origin.sample_index,
        origin.value_m,
        origin.unit.identifier.stable_id,
        origin.coordinate_reference,
        _event_key(origin.reference_event),
    )


def _parameter_key(
    identity: CMJMeasurementIdentity,
) -> tuple[tuple[str, object], ...]:
    ignored = {
        "source_signal_ids",
        "source_observation_ids",
        "source_measurement_identity_ids",
        "source_net_force_observation_id",
        "source_net_force_series_id",
        "source_system_weight_observation_id",
        "system_weight_segment",
        "source_net_force_system_weight_segment",
        "system_weight_qc",
        "source_net_force_system_weight_qc",
        "source_net_force_system_weight_quality_flags",
        "source_acceleration_source_net_force_system_weight_segment",
        "source_acceleration_source_net_force_system_weight_qc",
        "source_acceleration_source_net_force_system_weight_quality_flags",
        "source_velocity_source_acceleration_source_net_force_system_weight_segment",
        "source_velocity_source_acceleration_source_net_force_system_weight_qc",
        "source_velocity_source_acceleration_source_net_force_system_weight_quality_flags",
        "physical_mass_observation_id",
        "source_acceleration_observation_id",
        "source_acceleration_series_id",
        "source_velocity_observation_id",
        "source_velocity_series_id",
        "integration_interval",
        "initial_velocity_condition",
        "zero_velocity_reference",
        "displacement_origin",
    }
    return tuple(
        (entry.key, entry.value)
        for entry in identity.processing.method_parameters
        if entry.key not in ignored
    )


def _identity_differences(
    left: CMJMeasurementIdentity,
    right: CMJMeasurementIdentity,
) -> tuple[tuple[ComparabilityReasonCode, str], ...]:
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    if left.semantic.protocol_identity != right.semantic.protocol_identity:
        differences.append((ComparabilityReasonCode.PROTOCOL_MISMATCH, "protocol"))
    if left.semantic.construct.stable_id != right.semantic.construct.stable_id:
        differences.append((ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH, "construct"))
    if left.semantic.measurand.stable_id != right.semantic.measurand.stable_id:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "measurand"))
    if left.semantic.metric_definition.stable_id != right.semantic.metric_definition.stable_id:
        differences.append((ComparabilityReasonCode.IDENTITY_MISMATCH, "metric"))
    left_acquisition = left.acquisition
    right_acquisition = right.acquisition
    if (
        left_acquisition.device != right_acquisition.device
        or left_acquisition.measuring_system != right_acquisition.measuring_system
        or left_acquisition.hardware_firmware != right_acquisition.hardware_firmware
    ):
        differences.append((ComparabilityReasonCode.DEVICE_MISMATCH, "device"))
    if left_acquisition.arrangement != right_acquisition.arrangement:
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "arrangement"))
    if (
        left_acquisition.channel != right_acquisition.channel
        or left_acquisition.available_channels != right_acquisition.available_channels
    ):
        differences.append((ComparabilityReasonCode.CHANNEL_MISMATCH, "channel"))
    if left_acquisition.physical_axis != right_acquisition.physical_axis:
        differences.append((ComparabilityReasonCode.AXIS_MISMATCH, "axis"))
    if left_acquisition.reference_frame != right_acquisition.reference_frame:
        differences.append((ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH, "frame"))
    if left_acquisition.sign_convention != right_acquisition.sign_convention:
        differences.append((ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH, "sign"))
    if left_acquisition.timebase != right_acquisition.timebase:
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "timebase"))
    if left_acquisition.sampling != right_acquisition.sampling:
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "sampling"))
    if (
        left_acquisition.acquisition_software_version
        != right_acquisition.acquisition_software_version
    ):
        differences.append(
            (ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH, "acquisition software")
        )
    if (
        left_acquisition.calibration != right_acquisition.calibration
        or left_acquisition.zeroing != right_acquisition.zeroing
    ):
        differences.append((ComparabilityReasonCode.UNKNOWN_PROVENANCE, "calibration/zeroing"))
    if left_acquisition.processing_state != right_acquisition.processing_state:
        differences.append((ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "processing state"))
    if left_acquisition.combination_lineage != right_acquisition.combination_lineage:
        differences.append(
            (ComparabilityReasonCode.TOTAL_FORCE_CONSTRUCTION_MISMATCH, "combination lineage")
        )
    left_processing = left.processing
    right_processing = right.processing
    if left_processing.registered_operation != right_processing.registered_operation:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "operation"))
    if left_processing.integration_method != right_processing.integration_method:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "integration method"))
    if left_processing.filtering != right_processing.filtering:
        differences.append((ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, "filtering"))
    if left_processing.unit != right_processing.unit:
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "unit"))
    if left_processing.sign_convention != right_processing.sign_convention:
        differences.append((ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH, "processing sign"))
    if _parameter_key(left) != _parameter_key(right):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "method parameters"))
    return tuple(differences)


def _series_differences(
    left: CMJMechanicsSeries | None,
    right: CMJMechanicsSeries | None,
    left_interval: CMJIntegrationInterval | None,
    right_interval: CMJIntegrationInterval | None,
) -> tuple[tuple[ComparabilityReasonCode, str], ...]:
    if left is None and right is None:
        return ()
    if left is None or right is None:
        return ((ComparabilityReasonCode.MISSING_METADATA, "mechanics series"),)
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    if left.quantity != right.quantity:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "quantity"))
    if left.unit != right.unit:
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "series unit"))
    if left.physical_axis != right.physical_axis:
        differences.append((ComparabilityReasonCode.AXIS_MISMATCH, "series axis"))
    if left.reference_frame != right.reference_frame:
        differences.append((ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH, "series frame"))
    if left.sign_convention != right.sign_convention:
        differences.append((ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH, "series sign"))
    if left.system_contract != right.system_contract:
        differences.append((ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH, "system contract"))
    if left.operation != right.operation or left.integration_method != right.integration_method:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "series operation/integrator"))
    if (
        left.source_sample_count != right.source_sample_count
        or left.sample_start_index != right.sample_start_index
    ):
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "sample support"))
    if left.timebase != right.timebase:
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "series timebase"))
    if _interval_key(left_interval) != _interval_key(right_interval):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "integration interval"))
    if _condition_key(left.initial_velocity_condition) != _condition_key(
        right.initial_velocity_condition
    ):
        differences.append(
            (
                ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH,
                "zero-velocity reference",
            )
        )
    if _origin_key(left.displacement_origin) != _origin_key(right.displacement_origin):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "displacement origin"))
    return tuple(differences)


def assess_cmj_mechanics_comparability(
    request: CMJMechanicsComparabilityRequest,
) -> ComparabilityResult:
    """Apply the RES-37 claim-relative mechanics comparability rule."""

    differences = list(_identity_differences(request.left_identity, request.right_identity))
    differences.extend(
        _series_differences(
            request.left_series,
            request.right_series,
            request.left_interval,
            request.right_interval,
        )
    )
    if not differences:
        return ComparabilityResult(
            result_id=InstanceIdentifier(
                "comparability-result", f"{request.request_id.value}:comparable"
            ),
            request_id=request.request_id,
            state=ComparabilityState.COMPARABLE,
            reason_codes=(),
            conditions=(),
            transformations_required=(),
            missing_information=(),
            rule_reference=CMJ_MECHANICS_COMPARABILITY_RULE,
            evidence_references=(RES37_DECISION_IMPULSE_INTEGRATION,),
            decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
        )
    reasons = tuple(dict.fromkeys(reason for reason, _ in differences))
    state = (
        ComparabilityState.NOT_COMPARABLE
        if ComparabilityReasonCode.MEASURAND_MISMATCH in reasons
        else ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=(
            "all force processing, mass/gravity, integrator, interval, initial-condition, "
            "origin, event, timebase, filtering, and drift identities must match or have a "
            "registered bridge",
        ),
        transformations_required=(),
        missing_information=(),
        rule_reference=CMJ_MECHANICS_COMPARABILITY_RULE,
        evidence_references=(RES37_DECISION_IMPULSE_INTEGRATION,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _mechanics_parts(
    value: MechanicsResult,
) -> tuple[
    ScientificMeasurementObservation, CMJMechanicsSeries | None, CMJIntegrationInterval | None
]:
    if isinstance(value, NetVerticalImpulseResult):
        return value.observation, None, value.interval
    return value.observation, value.series, value.series.integration_interval


def compare_cmj_mechanics(
    left: MechanicsResult,
    right: MechanicsResult,
    *,
    claim: str,
    request_id: InstanceIdentifier,
) -> ComparabilityResult:
    """Compare mechanics results without flattening quantity or method identity."""

    left_observation, left_series, left_interval = _mechanics_parts(left)
    right_observation, right_series, right_interval = _mechanics_parts(right)
    if not isinstance(left_observation.identity, CMJMeasurementIdentity) or not isinstance(
        right_observation.identity, CMJMeasurementIdentity
    ):
        raise ValueError("mechanics observations must use CMJ measurement identities")
    return assess_cmj_mechanics_comparability(
        CMJMechanicsComparabilityRequest(
            request_id=request_id,
            left_observation_id=left_observation.observation_id,
            right_observation_id=right_observation.observation_id,
            left_identity=left_observation.identity,
            right_identity=right_observation.identity,
            left_series=left_series,
            right_series=right_series,
            left_interval=left_interval,
            right_interval=right_interval,
            claim=claim,
        )
    )


def refusal_for_cmj_mechanics_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Refuse only the mechanics comparison while preserving both results."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    mapping = {
        ComparabilityReasonCode.MEASURAND_MISMATCH: RefusalReasonCode.MEASURAND_MISMATCH,
        ComparabilityReasonCode.AXIS_MISMATCH: RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,
        ComparabilityReasonCode.MISSING_METADATA: RefusalReasonCode.MISSING_METADATA,
        ComparabilityReasonCode.METHOD_MISMATCH: (
            RefusalReasonCode.INTEGRATION_METHOD_NOT_REGISTERED
        ),
        ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH: (
            RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH
        ),
        ComparabilityReasonCode.PROTOCOL_MISMATCH: (RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH),
        ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH: (
            RefusalReasonCode.SIGN_CONVENTION_MISMATCH
        ),
        ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH: (
            RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED
        ),
        ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH: (
            RefusalReasonCode.AXIS_OR_FRAME_MISMATCH
        ),
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
        ),
        ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH: (
            RefusalReasonCode.SOURCE_PROCESSING_MISMATCH
        ),
        ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
        ),
    }
    reasons: list[RefusalReasonCode] = []
    for reason in result.reason_codes:
        try:
            normalized = ComparabilityReasonCode(reason)
        except ValueError:
            normalized = ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED
        mapped = mapping.get(normalized, RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)
        if mapped not in reasons:
            reasons.append(mapped)
    if not reasons:
        reasons.append(RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)
    return _mechanics_refusal(
        blocked_claim,
        tuple(reasons),
        result.missing_information or ("registered mechanics comparability bridge",),
        observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


# Operation-shaped aliases keep the public vocabulary explicit while retaining
# one implementation for each registered identity.
calculate_net_vertical_force = derive_net_vertical_force
calculate_net_vertical_impulse = integrate_net_vertical_impulse
integrate_supported_system_com_velocity = derive_supported_system_com_velocity
integrate_supported_system_com_relative_vertical_displacement = (
    derive_supported_system_com_relative_vertical_displacement
)


__all__ = [
    "RES37_SOFTWARE_VERSION",
    "CMJIntegrationInterval",
    "CMJIntegrationIntervalKind",
    "CMJMechanicalSystemContract",
    "CMJMechanicsComparabilityRequest",
    "CMJMechanicsQuantity",
    "CMJMechanicsSeries",
    "DisplacementOrigin",
    "InitialVelocityCondition",
    "MechanicalSystemContract",
    "NetVerticalForceResult",
    "NetVerticalImpulseResult",
    "QualifiedZeroVelocityReference",
    "SupportedSystemComAccelerationResult",
    "SupportedSystemComRelativeDisplacementResult",
    "SupportedSystemComVelocityResult",
    "assess_cmj_mechanics_comparability",
    "calculate_net_vertical_force",
    "calculate_net_vertical_impulse",
    "compare_cmj_mechanics",
    "derive_net_vertical_force",
    "derive_supported_system_com_acceleration",
    "derive_supported_system_com_relative_vertical_displacement",
    "derive_supported_system_com_velocity",
    "integrate_net_vertical_impulse",
    "integrate_supported_system_com_relative_vertical_displacement",
    "integrate_supported_system_com_velocity",
    "refusal_for_cmj_mechanics_comparability",
]
