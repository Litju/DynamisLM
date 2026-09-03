"""Registered, estimator-qualified CMJ ballistic jump-height estimates.

This module intentionally contains only the two RES-38 V1 estimators:
sample-attached flight-time height and qualified takeoff-velocity ballistic
apex rise.  It does not turn the RES-37 relative displacement coordinate into
an absolute or anatomical COM height.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.cmj.events import (
    CMJ_LANDING_ABSOLUTE_FORCE_METHOD,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
    CMJEventOccurrence,
    CMJEventOccurrenceStatus,
)
from dynamislm.measurement.cmj.identity import CMJ_REGISTRY_VERSION, CMJMeasurementIdentity
from dynamislm.measurement.cmj.mechanics import (
    CMJMechanicalSystemContract,
    QualifiedZeroVelocityReference,
    SupportedSystemComVelocityResult,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION,
    CMJ_FLIGHT_TIME_JUMP_HEIGHT_ESTIMATOR,
    CMJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION,
    CMJ_JUMP_HEIGHT_COMPARABILITY_RULE,
    CMJ_JUMP_HEIGHT_MEASURAND,
    CMJ_JUMP_HEIGHT_METRIC,
    CMJ_JUMP_HEIGHT_SCHEMA,
    CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION,
    CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION,
    CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT,
    CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_ESTIMATOR,
    CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_OPERATION,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION,
    CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION,
    CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
    METER,
    RES38_DECISION_CLASSIFICATION_COMPARABILITY,
    RES38_DECISION_FLIGHT_TIME_ESTIMATOR,
    RES38_DECISION_TAKEOFF_VELOCITY_ESTIMATOR,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    GravityReference,
    GravityReferenceType,
    _derived_identity,
    _merge_provenance,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    ScientificIdentifier,
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
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES38_SOFTWARE_VERSION = "dynamislm-res38-1.0.0"
_UNCERTAINTY_NOTE = "RES-38 model-estimate uncertainty is not assessed."


class JumpHeightEstimatorFamily(StrEnum):
    FLIGHT_TIME = "FLIGHT_TIME"
    TAKEOFF_VELOCITY = "TAKEOFF_VELOCITY"


class TakeoffVelocitySampleConvention(StrEnum):
    EVENT_SAMPLE = "EVENT_SAMPLE"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class JumpHeightEstimand:
    """Shared physical quantity targeted by the two distinct estimator methods."""

    reference: RegistryReference
    description: str

    def __post_init__(self) -> None:
        if self.reference.stable_id != CMJ_JUMP_HEIGHT_MEASURAND.stable_id:
            raise ValueError("RES-38 estimand must use the registered jump-height measurand")
        if not self.description.strip():
            raise ValueError("estimand description must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class JumpHeightEstimatorMethod:
    """Identity and material assumptions for one registered estimator."""

    reference: RegistryReference
    operation: RegistryReference
    family: JumpHeightEstimatorFamily
    estimand: JumpHeightEstimand
    equation: str
    assumptions: tuple[RegistryReference, ...]
    evidence_decision: RegistryReference
    claim_ceiling: str

    def __post_init__(self) -> None:
        if self.reference.identifier.object_type != "estimator":
            raise ValueError("estimator method must use an estimator registry reference")
        if self.operation.identifier.object_type != "registered-operation":
            raise ValueError("estimator method must use a registered operation")
        if not isinstance(self.family, JumpHeightEstimatorFamily):
            raise ValueError("estimator family must be registered")
        if not isinstance(self.estimand, JumpHeightEstimand):
            raise ValueError("estimator must identify a JumpHeightEstimand")
        if not self.equation.strip() or not self.claim_ceiling.strip():
            raise ValueError("estimator equation and claim ceiling must not be empty")
        require_tuple(self.assumptions, "assumptions")
        if not self.assumptions or len(set(self.assumptions)) != len(self.assumptions):
            raise ValueError("estimator assumptions must be non-empty and unique")
        if self.evidence_decision.identifier.object_type != "decision-record":
            raise ValueError("estimator evidence_decision must be a decision record")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class JumpHeightEstimatorParameters:
    """Serialized inputs and conventions for one scalar estimator result."""

    gravity: GravityReference
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_timebase: SignalTimebase
    takeoff_event_id: InstanceIdentifier
    takeoff_sample_index: int
    takeoff_event_time_s: float
    landing_event_id: InstanceIdentifier | None = None
    landing_sample_index: int | None = None
    landing_event_time_s: float | None = None
    flight_time_s: float | None = None
    takeoff_velocity_sample_convention: RegistryReference | None = None
    takeoff_velocity_sample_index: int | None = None
    takeoff_velocity_m_per_s: float | None = None
    source_velocity_observation_id: InstanceIdentifier | None = None
    source_velocity_series_id: InstanceIdentifier | None = None
    source_velocity_initial_condition: QualifiedZeroVelocityReference | None = None
    source_velocity_operation: RegistryReference | None = None
    source_velocity_integration_method: RegistryReference | None = None
    system_contract: CMJMechanicalSystemContract | None = None
    assumptions: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.gravity, GravityReference):
            raise ValueError("jump-height parameters require an explicit gravity reference")
        for field_name in (
            "source_observation_id",
            "source_signal_id",
            "source_artifact_id",
            "source_acquisition_id",
            "takeoff_event_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, InstanceIdentifier):
                raise ValueError(f"{field_name} must be an InstanceIdentifier")
        if self.source_observation_id.instance_type != "observation":
            raise ValueError("source_observation_id must identify an observation")
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("source_signal_id must identify a signal")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("source_artifact_id must identify an artifact")
        if self.source_acquisition_id.instance_type != "acquisition":
            raise ValueError("source_acquisition_id must identify an acquisition")
        if self.takeoff_event_id.instance_type != "event-occurrence":
            raise ValueError("takeoff_event_id must identify an event occurrence")
        if not isinstance(self.source_measurement_identity_id, ScientificIdentifier):
            raise ValueError("source_measurement_identity_id must be a ScientificIdentifier")
        if not isinstance(self.source_timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("source_timebase must be a registered timebase")
        _nonnegative_index(self.takeoff_sample_index, "takeoff_sample_index")
        _finite(self.takeoff_event_time_s, "takeoff_event_time_s")
        landing_values = (
            self.landing_event_id,
            self.landing_sample_index,
            self.landing_event_time_s,
            self.flight_time_s,
        )
        if any(value is not None for value in landing_values) and not all(
            value is not None for value in landing_values
        ):
            raise ValueError("flight-time landing parameters must be complete")
        if self.landing_event_id is not None:
            if self.landing_event_id.instance_type != "event-occurrence":
                raise ValueError("landing_event_id must identify an event occurrence")
            if self.landing_sample_index is None or self.landing_event_time_s is None:
                raise AssertionError("validated landing parameters must be present")
            _nonnegative_index(self.landing_sample_index, "landing_sample_index")
            _finite(self.landing_event_time_s, "landing_event_time_s")
            if self.flight_time_s is None or not math.isfinite(self.flight_time_s):
                raise ValueError("flight_time_s must be finite when landing is present")
        if self.takeoff_velocity_sample_convention is not None:
            if (
                self.takeoff_velocity_sample_convention.stable_id
                != CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION.stable_id
            ):
                raise ValueError("takeoff velocity sample convention is not registered")
            if self.takeoff_velocity_sample_index is None:
                raise ValueError("takeoff velocity sample index is required with its convention")
            _nonnegative_index(self.takeoff_velocity_sample_index, "takeoff_velocity_sample_index")
        if self.takeoff_velocity_m_per_s is not None:
            _finite(self.takeoff_velocity_m_per_s, "takeoff_velocity_m_per_s")
        velocity_ids = (self.source_velocity_observation_id, self.source_velocity_series_id)
        if any(value is not None for value in velocity_ids) and not all(
            value is not None for value in velocity_ids
        ):
            raise ValueError("velocity source identifiers must be complete")
        if self.source_velocity_observation_id is not None:
            if self.source_velocity_observation_id.instance_type != "observation":
                raise ValueError("source_velocity_observation_id must identify an observation")
            if self.source_velocity_series_id is None:
                raise AssertionError("validated velocity series identifier must be present")
            if self.source_velocity_series_id.instance_type != "signal":
                raise ValueError("source_velocity_series_id must identify a signal")
        if self.source_velocity_initial_condition is not None and not isinstance(
            self.source_velocity_initial_condition, QualifiedZeroVelocityReference
        ):
            raise ValueError("source velocity initial condition must be qualified")
        require_tuple(self.assumptions, "assumptions")
        if len(set(self.assumptions)) != len(self.assumptions):
            raise ValueError("assumptions must not contain duplicates")


JUMP_HEIGHT_ESTIMAND = JumpHeightEstimand(
    CMJ_JUMP_HEIGHT_MEASURAND,
    "vertical ballistic takeoff-to-apex rise",
)

CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD = JumpHeightEstimatorMethod(
    reference=CMJ_FLIGHT_TIME_JUMP_HEIGHT_ESTIMATOR,
    operation=CMJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION,
    family=JumpHeightEstimatorFamily.FLIGHT_TIME,
    estimand=JUMP_HEIGHT_ESTIMAND,
    equation="h = g_local * flight_time_s^2 / 8",
    assumptions=(
        CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION,
        CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION,
        CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION,
        CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION,
    ),
    evidence_decision=RES38_DECISION_FLIGHT_TIME_ESTIMATOR,
    claim_ceiling=(
        "estimator-qualified supported-trial flight-time ballistic height; "
        "not automatically anatomical athlete COM jump height"
    ),
)

CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD = JumpHeightEstimatorMethod(
    reference=CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_ESTIMATOR,
    operation=CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_OPERATION,
    family=JumpHeightEstimatorFamily.TAKEOFF_VELOCITY,
    estimand=JUMP_HEIGHT_ESTIMAND,
    equation="h = takeoff_velocity_m_per_s^2 / (2 * g_local)",
    assumptions=(
        CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION,
        CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION,
        CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION,
        CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION,
    ),
    evidence_decision=RES38_DECISION_TAKEOFF_VELOCITY_ESTIMATOR,
    claim_ceiling=(
        "supported-system COM ballistic apex rise above takeoff; "
        "loaded trials are not automatically athlete-only COM height"
    ),
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJJumpHeightResult:
    """One scalar jump-height estimate with its full method-qualified identity."""

    observation: ScientificMeasurementObservation
    method: JumpHeightEstimatorMethod
    parameters: JumpHeightEstimatorParameters
    takeoff_event: CMJEventOccurrence
    landing_event: CMJEventOccurrence | None = None
    source_velocity: SupportedSystemComVelocityResult | None = None

    def __post_init__(self) -> None:
        if self.method not in (
            CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD,
            CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD,
        ):
            raise ValueError("result method must be one of the registered RES-38 estimators")
        _assert_output_identity(self.observation, self.method, self.parameters)
        if self.parameters.assumptions != self.method.assumptions:
            raise ValueError("result parameters must preserve method assumptions")
        _assert_event(self.takeoff_event, CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD, "takeoff")
        if (
            self.parameters.gravity.reference_type
            is not GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION
        ):
            raise ValueError("jump-height result must use the registered local gravity path")
        if self.method.family is JumpHeightEstimatorFamily.FLIGHT_TIME:
            if self.landing_event is None or self.source_velocity is not None:
                raise ValueError("flight-time result requires landing and no velocity source")
            _assert_event(self.landing_event, CMJ_LANDING_ABSOLUTE_FORCE_METHOD, "landing")
            _assert_shared_event_source(self.takeoff_event, self.landing_event)
            _assert_flight_parameters(self.parameters, self.takeoff_event, self.landing_event)
            if self.parameters.source_observation_id != self.takeoff_event.source_observation_id:
                raise ValueError("flight result source observation must match takeoff event")
        elif self.method.family is JumpHeightEstimatorFamily.TAKEOFF_VELOCITY:
            if self.landing_event is not None or self.source_velocity is None:
                raise ValueError("takeoff-velocity result requires velocity and no landing")
            _assert_velocity_linkage(
                self.source_velocity,
                self.takeoff_event,
                self.parameters,
                raise_errors=True,
            )
        else:
            raise ValueError("unregistered jump-height estimator family")
        _assert_output_value(self.observation, self.method, self.parameters, self.source_velocity)
        _assert_output_run(self.observation, self.method)

    @property
    def value_m(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("jump-height result is not a numeric scalar")
        return float(value.value)

    @property
    def estimator_family(self) -> JumpHeightEstimatorFamily:
        return self.method.family

    @property
    def estimator(self) -> RegistryReference:
        return self.method.reference


# Short type-level alias; the public operation names remain estimator-qualified.
JumpHeightEstimate = CMJJumpHeightResult


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJJumpHeightComparabilityRequest:
    """Claim-relative comparison request for two estimator-qualified outputs."""

    request_id: InstanceIdentifier
    left: CMJJumpHeightResult
    right: CMJJumpHeightResult
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("request_id must identify a comparability request")
        if self.left.observation.observation_id == self.right.observation.observation_id:
            raise ValueError("jump-height comparability requires distinct observations")
        if not self.claim.strip():
            raise ValueError("claim must not be empty")
        require_tuple(self.requested_transformations, "requested_transformations")


def estimate_flight_time_jump_height(
    takeoff: CMJEventOccurrence | None,
    landing: CMJEventOccurrence | None,
    gravity: GravityReference | None,
    *,
    source_observation: ScientificMeasurementObservation | None = None,
) -> CMJJumpHeightResult | RefusalResult:
    """Estimate flight-time ballistic height from two exact source events."""

    claim = "estimate CMJ jump height by registered flight-time ballistic method"
    if takeoff is None:
        return _jump_refusal(claim, (RefusalReasonCode.TAKEOFF_REQUIRED,), ("takeoff event",))
    if landing is None:
        return _jump_refusal(claim, (RefusalReasonCode.LANDING_REQUIRED,), ("landing event",))
    if not isinstance(takeoff, CMJEventOccurrence) or not isinstance(landing, CMJEventOccurrence):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("registered CMJEventOccurrence inputs",),
        )
    event_refusal = _event_refusal_if_invalid(
        takeoff, CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD, "takeoff", claim
    )
    if event_refusal is not None:
        return event_refusal
    event_refusal = _event_refusal_if_invalid(
        landing, CMJ_LANDING_ABSOLUTE_FORCE_METHOD, "landing", claim
    )
    if event_refusal is not None:
        return event_refusal
    source_refusal = _source_observation_refusal(source_observation, takeoff, claim)
    if source_refusal is not None:
        return source_refusal
    assert source_observation is not None
    source_refusal = _shared_event_source_refusal(takeoff, landing, claim)
    if source_refusal is not None:
        return source_refusal
    gravity_refusal = _gravity_refusal(gravity, claim)
    if gravity_refusal is not None:
        return gravity_refusal
    assert gravity is not None
    duration = landing.event_time_s - takeoff.event_time_s
    if duration <= 0 or not math.isfinite(duration) or landing.sample_index <= takeoff.sample_index:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.FLIGHT_INTERVAL_INVALID,),
            ("positive recorded landing-minus-takeoff event interval",),
            observation_ids=(source_observation.observation_id,),
        )
    if source_observation.identity != takeoff.source_measurement_identity:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("source observation identity equal to the event source identity",),
            observation_ids=(source_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not isinstance(source_observation.identity, CMJMeasurementIdentity):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("CMJ source observation identity",),
            observation_ids=(source_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = JumpHeightEstimatorParameters(
        gravity=gravity,
        source_observation_id=takeoff.source_observation_id,
        source_signal_id=takeoff.source_signal_id,
        source_artifact_id=takeoff.source_artifact_id,
        source_acquisition_id=takeoff.source_acquisition_id,
        source_measurement_identity_id=takeoff.source_measurement_identity.identity_id,
        source_timebase=takeoff.source_timebase,
        takeoff_event_id=takeoff.occurrence_id,
        takeoff_sample_index=takeoff.sample_index,
        takeoff_event_time_s=takeoff.event_time_s,
        landing_event_id=landing.occurrence_id,
        landing_sample_index=landing.sample_index,
        landing_event_time_s=landing.event_time_s,
        flight_time_s=duration,
        assumptions=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.assumptions,
    )
    value_m = gravity.value_m_per_s2 * duration**2 / 8.0
    return _build_result(
        method=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD,
        parameters=parameters,
        takeoff=takeoff,
        landing=landing,
        source_velocity=None,
        source_identity=source_observation.identity,
        source_context=source_observation.context,
        base_provenance=_merge_provenance(
            _merge_provenance(takeoff.provenance, landing.provenance),
            source_observation.provenance,
        ),
        value_m=value_m,
        source_entities=(
            source_observation.observation_id,
            takeoff.occurrence_id,
            landing.occurrence_id,
            takeoff.source_signal_id,
        ),
    )


def estimate_takeoff_velocity_jump_height(
    velocity: SupportedSystemComVelocityResult | None,
    takeoff: CMJEventOccurrence | None,
    gravity: GravityReference | None,
    *,
    sample_convention: TakeoffVelocitySampleConvention = (
        TakeoffVelocitySampleConvention.EVENT_SAMPLE
    ),
) -> CMJJumpHeightResult | RefusalResult:
    """Estimate supported-system ballistic apex rise from qualified takeoff velocity."""

    claim = "estimate CMJ jump height by qualified takeoff-velocity ballistic method"
    if takeoff is None:
        return _jump_refusal(claim, (RefusalReasonCode.TAKEOFF_REQUIRED,), ("takeoff event",))
    if velocity is None or not isinstance(velocity, SupportedSystemComVelocityResult):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.TAKEOFF_VELOCITY_REQUIRED,),
            ("RES-46-authorized SupportedSystemComVelocityResult",),
        )
    if not isinstance(takeoff, CMJEventOccurrence):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("registered CMJEventOccurrence takeoff input",),
        )
    event_refusal = _event_refusal_if_invalid(
        takeoff, CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD, "takeoff", claim
    )
    if event_refusal is not None:
        return event_refusal
    gravity_refusal = _gravity_refusal(gravity, claim)
    if gravity_refusal is not None:
        return gravity_refusal
    assert gravity is not None
    if sample_convention is not TakeoffVelocitySampleConvention.EVENT_SAMPLE:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.TAKEOFF_VELOCITY_SAMPLE_UNRESOLVED,),
            (CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION.stable_id,),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    condition = velocity.initial_velocity_condition
    if not isinstance(condition, QualifiedZeroVelocityReference):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,),
            ("RES-46 QualifiedZeroVelocityReference",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not condition.is_authorized:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,),
            ("adjudicated RES-46 zero-velocity reference",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED,
        )
    linkage_refusal = _velocity_linkage_refusal(velocity, takeoff, claim)
    if linkage_refusal is not None:
        return linkage_refusal
    mass_gravity_refusal = _velocity_gravity_refusal(velocity, gravity, claim)
    if mass_gravity_refusal is not None:
        return mass_gravity_refusal
    if not velocity.system_contract.is_authorized:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED,),
            ("authorized supported-system mechanics contract",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not isinstance(velocity.observation.identity, CMJMeasurementIdentity):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("CMJ measurement identity on the supported-system velocity observation",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    local_index = takeoff.sample_index - velocity.series.sample_start_index
    if not 0 <= local_index < len(velocity.samples):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.TAKEOFF_VELOCITY_SAMPLE_UNRESOLVED,),
            ("takeoff.sample_index inside velocity series source support",),
            observation_ids=(velocity.observation.observation_id,),
        )
    takeoff_velocity = velocity.samples[local_index]
    if takeoff_velocity < 0:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.BALLISTIC_ASSUMPTION_UNSUPPORTED,),
            ("upward-positive nonnegative velocity at the takeoff event sample",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    parameters = JumpHeightEstimatorParameters(
        gravity=gravity,
        source_observation_id=takeoff.source_observation_id,
        source_signal_id=takeoff.source_signal_id,
        source_artifact_id=takeoff.source_artifact_id,
        source_acquisition_id=takeoff.source_acquisition_id,
        source_measurement_identity_id=takeoff.source_measurement_identity.identity_id,
        source_timebase=takeoff.source_timebase,
        takeoff_event_id=takeoff.occurrence_id,
        takeoff_sample_index=takeoff.sample_index,
        takeoff_event_time_s=takeoff.event_time_s,
        takeoff_velocity_sample_convention=CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
        takeoff_velocity_sample_index=takeoff.sample_index,
        takeoff_velocity_m_per_s=takeoff_velocity,
        source_velocity_observation_id=velocity.observation.observation_id,
        source_velocity_series_id=velocity.series.series_id,
        source_velocity_initial_condition=condition,
        source_velocity_operation=velocity.series.operation,
        source_velocity_integration_method=velocity.series.integration_method,
        system_contract=velocity.system_contract,
        assumptions=CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD.assumptions,
    )
    value_m = takeoff_velocity**2 / (2.0 * gravity.value_m_per_s2)
    return _build_result(
        method=CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD,
        parameters=parameters,
        takeoff=takeoff,
        landing=None,
        source_velocity=velocity,
        source_identity=velocity.observation.identity,
        source_context=velocity.observation.context,
        base_provenance=_merge_provenance(velocity.observation.provenance, takeoff.provenance),
        value_m=value_m,
        source_entities=(
            velocity.observation.observation_id,
            velocity.series.series_id,
            *velocity.series.source_observation_ids,
            *velocity.series.source_signal_ids,
            takeoff.occurrence_id,
        ),
    )


def defer_com_displacement_jump_height(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    """Keep the RES-37 relative displacement boundary explicit in V1."""

    return _jump_refusal(
        "estimate CMJ jump height by COM displacement",
        (RefusalReasonCode.COM_DISPLACEMENT_ESTIMATOR_DEFERRED,),
        (
            "registered apex/phase authority",
            "absolute or anatomical COM origin",
            "registered drift policy",
        ),
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


def refuse_unregistered_cmj_jump_height_estimator(
    *,
    blocked_claim: str = "estimate generic CMJ jump height without estimator qualification",
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    """Refuse a generic jump-height claim that names no registered estimator."""

    return _jump_refusal(
        blocked_claim,
        (RefusalReasonCode.JUMP_HEIGHT_ESTIMATOR_NOT_REGISTERED,),
        ("one of the registered RES-38 estimator methods",),
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


def assess_cmj_jump_height_comparability(
    request: CMJJumpHeightComparabilityRequest,
) -> ComparabilityResult:
    """Apply estimator-aware comparability without using numeric value equality."""

    left = request.left
    right = request.right
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    if left.method.estimand.reference != right.method.estimand.reference:
        differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "estimand"))
    if left.method.reference != right.method.reference:
        differences.extend(
            (
                (ComparabilityReasonCode.ESTIMATOR_MISMATCH, "estimator family"),
                (ComparabilityReasonCode.BRIDGE_NOT_REGISTERED, "estimator bridge"),
            )
        )
    if left.method.operation != right.method.operation:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "registered operation"))
    differences.extend(_jump_method_differences(left, right))
    reasons = tuple(dict.fromkeys(reason for reason, _ in differences))
    if not reasons:
        return _comparability_result(request, ComparabilityState.COMPARABLE)
    if ComparabilityReasonCode.MEASURAND_MISMATCH in reasons:
        return _comparability_result(request, ComparabilityState.NOT_COMPARABLE, reasons=reasons)
    return _comparability_result(
        request,
        ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
        reasons=reasons,
        conditions=(
            "a registered estimator-method, event, gravity, mechanics, or system bridge "
            "is required before the requested claim",
        ),
    )


def compare_cmj_jump_height_estimates(
    left: CMJJumpHeightResult,
    right: CMJJumpHeightResult,
    *,
    claim: str,
    request_id: InstanceIdentifier,
) -> ComparabilityResult:
    """Convenience constructor for estimator-aware comparison."""

    return assess_cmj_jump_height_comparability(
        CMJJumpHeightComparabilityRequest(
            request_id=request_id,
            left=left,
            right=right,
            claim=claim,
        )
    )


def refusal_for_cmj_jump_height_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Block only the unsupported comparison while preserving both estimates."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    mapping = {
        ComparabilityReasonCode.MEASURAND_MISMATCH: RefusalReasonCode.MEASURAND_MISMATCH,
        ComparabilityReasonCode.ESTIMATOR_MISMATCH: RefusalReasonCode.ESTIMATOR_MISMATCH,
        ComparabilityReasonCode.METHOD_MISMATCH: RefusalReasonCode.ESTIMATOR_MISMATCH,
        ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH: (
            RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH
        ),
        ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH: (
            RefusalReasonCode.EVENT_DEFINITION_MISMATCH
        ),
        ComparabilityReasonCode.EVENT_METHOD_MISMATCH: RefusalReasonCode.EVENT_METHOD_MISMATCH,
        ComparabilityReasonCode.EVENT_PARAMETER_MISMATCH: (
            RefusalReasonCode.EVENT_PARAMETER_MISMATCH
        ),
        ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH: (
            RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH
        ),
        ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH: (
            RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED
        ),
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
        ),
        ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH: (
            RefusalReasonCode.SOURCE_PROCESSING_MISMATCH
        ),
    }
    reason_codes: list[RefusalReasonCode] = []
    for value in result.reason_codes:
        try:
            reason = ComparabilityReasonCode(value)
        except ValueError:
            mapped = RefusalReasonCode.COMPARABILITY_NOT_REGISTERED
        else:
            mapped = mapping.get(reason, RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)
        if mapped not in reason_codes:
            reason_codes.append(mapped)
    if not reason_codes:
        reason_codes.append(RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)
    return _jump_refusal(
        blocked_claim,
        tuple(reason_codes),
        result.missing_information or ("registered estimator comparability bridge",),
        observation_ids=observation_ids,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
    )


def _build_result(
    *,
    method: JumpHeightEstimatorMethod,
    parameters: JumpHeightEstimatorParameters,
    takeoff: CMJEventOccurrence,
    landing: CMJEventOccurrence | None,
    source_velocity: SupportedSystemComVelocityResult | None,
    source_identity: CMJMeasurementIdentity,
    source_context: ObservationContext,
    base_provenance: Provenance,
    value_m: float,
    source_entities: tuple[InstanceIdentifier, ...],
) -> CMJJumpHeightResult:
    if not base_provenance.source_artifacts:
        raise ValueError("jump-height estimate requires source artifact provenance")
    source_signal = source_identity.acquisition.sign_convention
    metadata = _processing_parameters(
        method,
        parameters,
        takeoff,
        landing,
        source_velocity,
        source_identity,
    )
    digest = canonical_hash(
        {
            "method": method,
            "parameters": parameters,
            "value_m": value_m,
            "source_entities": source_entities,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = InstanceIdentifier("observation", f"cmj-jump-height:{digest}")
    artifact_id = InstanceIdentifier("artifact", f"cmj-jump-height:{digest}")
    processing_run_id = InstanceIdentifier("processing-run", f"cmj-jump-height:{digest}")
    result_id = InstanceIdentifier("result", f"cmj-jump-height:{digest}")
    identity_id = ScientificIdentifier(
        "dynamislm",
        "measurement-identity",
        f"cmj-jump-height-{method.family.value.lower()}-{digest}",
        CMJ_REGISTRY_VERSION,
    )
    identity = _derived_identity(
        source_identity,
        identity_id=identity_id,
        measurand=CMJ_JUMP_HEIGHT_MEASURAND,
        metric=CMJ_JUMP_HEIGHT_METRIC,
        processing=ProcessingIdentity(
            event_definitions=(
                takeoff.definition.reference,
                *((landing.definition.reference,) if landing is not None else ()),
            ),
            estimator=method.reference,
            registered_operation=method.operation,
            method_parameters=metadata,
            unit=METER,
            sign_convention=source_signal,
        ),
        processing_method=method.operation,
        software_version=RES38_SOFTWARE_VERSION,
    )
    output_artifact = SourceArtifact(
        artifact_id=artifact_id,
        content_digest=canonical_hash(
            {"value_m": value_m, "unit": METER, "method": method, "parameters": parameters}
        ),
        media_type="application/vnd.dynamislm.cmj.jump-height-estimate",
        immutable=True,
    )
    source_artifact_ids = tuple(
        sorted(
            (artifact.artifact_id for artifact in base_provenance.source_artifacts),
            key=_qualified,
        )
    )
    processing_run = ProcessingRun(
        processing_run_id=processing_run_id,
        source_artifact_ids=source_artifact_ids,
        method=method.operation,
        parameters=metadata,
        software_version=RES38_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_jump_run(
        base_provenance,
        processing_run=processing_run,
        output_entity_id=observation_id,
        source_entity_ids=_unique(source_entities),
        source_acquisition_ids=tuple(
            sorted(
                (acquisition.acquisition_id for acquisition in base_provenance.acquisitions),
                key=_qualified,
            )
        ),
        output_artifact=output_artifact,
        supported_by=(method.evidence_decision, RES38_DECISION_CLASSIFICATION_COMPARABILITY),
        evidence_references=(
            EvidenceReference(method.evidence_decision, "registered RES-38 estimator method"),
            EvidenceReference(
                RES38_DECISION_CLASSIFICATION_COMPARABILITY,
                "model-estimate and comparability contract",
            ),
        ),
        recorded_at=source_context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=source_context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=ScalarValue(value_m),
            unit=METER,
            classification=ScientificClassification(
                value_origin=ValueOrigin.MODEL_ESTIMATE,
                scientific_roles=(ScientificRole.PERFORMANCE_OUTCOME,),
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=_UNCERTAINTY_NOTE,
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return CMJJumpHeightResult(
        observation=observation,
        method=method,
        parameters=parameters,
        takeoff_event=takeoff,
        landing_event=landing,
        source_velocity=source_velocity,
    )


def _processing_parameters(
    method: JumpHeightEstimatorMethod,
    parameters: JumpHeightEstimatorParameters,
    takeoff: CMJEventOccurrence,
    landing: CMJEventOccurrence | None,
    source_velocity: SupportedSystemComVelocityResult | None,
    source_identity: CMJMeasurementIdentity,
) -> tuple[MetadataEntry, ...]:
    entries = [
        MetadataEntry("estimator_id", method.reference.stable_id),
        MetadataEntry("operation_id", method.operation.stable_id),
        MetadataEntry("estimand_id", method.estimand.reference.stable_id),
        MetadataEntry("output_schema", CMJ_JUMP_HEIGHT_SCHEMA.stable_id),
        MetadataEntry("equation", method.equation),
        MetadataEntry("estimator_parameters", canonical_json(parameters)),
        MetadataEntry("assumptions", canonical_json(method.assumptions)),
        MetadataEntry("gravity", canonical_json(parameters.gravity)),
        MetadataEntry("gravity_value_m_per_s2", parameters.gravity.value_m_per_s2),
        MetadataEntry("gravity_reference_type", parameters.gravity.reference_type.value),
        MetadataEntry("gravity_source", parameters.gravity.source.stable_id),
        MetadataEntry("source_observation_id", parameters.source_observation_id.qualified),
        MetadataEntry("source_signal_id", parameters.source_signal_id.qualified),
        MetadataEntry("source_artifact_id", parameters.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", parameters.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", parameters.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("source_timebase", canonical_json(parameters.source_timebase)),
        MetadataEntry("source_filtering", canonical_json(source_identity.processing.filtering)),
        MetadataEntry("takeoff_event_id", takeoff.occurrence_id.qualified),
        MetadataEntry("takeoff_event_definition", takeoff.definition.reference.stable_id),
        MetadataEntry("takeoff_detector_method", takeoff.detector_method.reference.stable_id),
        MetadataEntry("takeoff_detector_parameters", canonical_json(takeoff.detector_parameters)),
        MetadataEntry("takeoff_sample_index", takeoff.sample_index),
        MetadataEntry("takeoff_event_time_s", takeoff.event_time_s),
        MetadataEntry(
            "landing_event_id",
            landing.occurrence_id.qualified if landing is not None else "not_applicable",
        ),
        MetadataEntry(
            "landing_event_definition",
            landing.definition.reference.stable_id if landing is not None else "not_applicable",
        ),
        MetadataEntry(
            "landing_detector_method",
            landing.detector_method.reference.stable_id
            if landing is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "landing_detector_parameters",
            canonical_json(landing.detector_parameters)
            if landing is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "landing_sample_index",
            landing.sample_index if landing is not None else "not_applicable",
        ),
        MetadataEntry(
            "landing_event_time_s",
            landing.event_time_s if landing is not None else "not_applicable",
        ),
        MetadataEntry(
            "flight_time_s",
            parameters.flight_time_s if parameters.flight_time_s is not None else "not_applicable",
        ),
        MetadataEntry(
            "takeoff_velocity_sample_convention",
            parameters.takeoff_velocity_sample_convention.stable_id
            if parameters.takeoff_velocity_sample_convention is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "takeoff_velocity_sample_index",
            parameters.takeoff_velocity_sample_index
            if parameters.takeoff_velocity_sample_index is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "takeoff_velocity_m_per_s",
            parameters.takeoff_velocity_m_per_s
            if parameters.takeoff_velocity_m_per_s is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "source_velocity_observation_id",
            parameters.source_velocity_observation_id.qualified
            if parameters.source_velocity_observation_id is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "source_velocity_series_id",
            parameters.source_velocity_series_id.qualified
            if parameters.source_velocity_series_id is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "source_velocity_operation",
            parameters.source_velocity_operation.stable_id
            if parameters.source_velocity_operation is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "source_velocity_integration_method",
            parameters.source_velocity_integration_method.stable_id
            if parameters.source_velocity_integration_method is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "source_velocity_initial_condition",
            canonical_json(parameters.source_velocity_initial_condition)
            if parameters.source_velocity_initial_condition is not None
            else "not_applicable",
        ),
        MetadataEntry(
            "system_contract",
            canonical_json(parameters.system_contract)
            if parameters.system_contract is not None
            else "not_applicable",
        ),
        MetadataEntry("event_time_semantics", "recorded event_time_s difference; no interpolation"),
        MetadataEntry("filtering", "none"),
        MetadataEntry("interpolation", "none"),
        MetadataEntry("resampling", "none"),
        MetadataEntry("drift_correction", "none"),
        MetadataEntry("standard_gravity_substitution", False),
        MetadataEntry("source_velocity_present", source_velocity is not None),
    ]
    return tuple(entries)


def _provenance_with_jump_run(
    base: Provenance,
    *,
    processing_run: ProcessingRun,
    output_entity_id: InstanceIdentifier,
    source_entity_ids: tuple[InstanceIdentifier, ...],
    source_acquisition_ids: tuple[InstanceIdentifier, ...],
    output_artifact: SourceArtifact,
    supported_by: tuple[RegistryReference, ...],
    evidence_references: tuple[EvidenceReference, ...],
    recorded_at: datetime_module.datetime | None,
) -> Provenance:
    """Append a scalar estimate run while naming event/entity lineage explicitly."""

    artifacts = _append_unique(base.source_artifacts, (output_artifact,))
    runs = _append_unique(base.processing_runs, (processing_run,))
    evidence = _append_unique(base.evidence_references, evidence_references)
    edges = list(base.lineage_edges)
    for source_entity_id in source_entity_ids:
        _append_edge(
            edges,
            LineageEdge(
                source_entity_id.qualified,
                processing_run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
        )
    for source_artifact_id in processing_run.source_artifact_ids:
        _append_edge(
            edges,
            LineageEdge(
                source_artifact_id.qualified,
                processing_run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
        )
    for source_acquisition_id in source_acquisition_ids:
        _append_edge(
            edges,
            LineageEdge(
                source_acquisition_id.qualified,
                processing_run.processing_run_id.qualified,
                LineageRelation.PROCESSED_AS,
            ),
        )
    for reference in supported_by:
        _append_edge(
            edges,
            LineageEdge(
                reference.stable_id,
                processing_run.processing_run_id.qualified,
                LineageRelation.SUPPORTED_BY,
            ),
        )
    _append_edge(
        edges,
        LineageEdge(
            processing_run.processing_run_id.qualified,
            output_artifact.artifact_id.qualified,
            LineageRelation.PRODUCED,
        ),
    )
    _append_edge(
        edges,
        LineageEdge(
            processing_run.processing_run_id.qualified,
            output_entity_id.qualified,
            LineageRelation.PRODUCED,
        ),
    )
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_entity_id.value),
        source_artifacts=artifacts,
        acquisitions=base.acquisitions,
        processing_runs=runs,
        lineage_edges=tuple(edges),
        evidence_references=evidence,
        metrological_traceability=base.metrological_traceability,
        recorded_at=recorded_at,
    )


def _jump_method_differences(
    left: CMJJumpHeightResult,
    right: CMJJumpHeightResult,
) -> tuple[tuple[ComparabilityReasonCode, str], ...]:
    differences: list[tuple[ComparabilityReasonCode, str]] = []
    left_parameters = left.parameters
    right_parameters = right.parameters
    if left_parameters.gravity != right_parameters.gravity:
        differences.append((ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH, "gravity"))
    if (
        left.observation.identity.version.processing_method
        != right.observation.identity.version.processing_method
        or left.observation.identity.version.method_registry_version
        != right.observation.identity.version.method_registry_version
        or left.observation.identity.version.software_version
        != right.observation.identity.version.software_version
    ):
        differences.append((ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "estimator version"))
    if left_parameters.source_timebase != right_parameters.source_timebase:
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "source timebase"))
    left_metadata = {
        entry.key: entry.value for entry in left.observation.identity.processing.method_parameters
    }
    right_metadata = {
        entry.key: entry.value for entry in right.observation.identity.processing.method_parameters
    }
    for key in (
        "event_time_semantics",
        "filtering",
        "interpolation",
        "resampling",
        "drift_correction",
        "source_filtering",
    ):
        if left_metadata.get(key) != right_metadata.get(key):
            differences.append((ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, key))
    if _event_method_key(left.takeoff_event) != _event_method_key(right.takeoff_event):
        differences.append((ComparabilityReasonCode.EVENT_METHOD_MISMATCH, "takeoff detector"))
    if left.landing_event is None or right.landing_event is None:
        if left.landing_event is not right.landing_event:
            differences.append((ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH, "landing event"))
    elif _event_method_key(left.landing_event) != _event_method_key(right.landing_event):
        differences.append((ComparabilityReasonCode.EVENT_METHOD_MISMATCH, "landing detector"))
    if _protocol_key(left.observation.identity) != _protocol_key(right.observation.identity):
        differences.append((ComparabilityReasonCode.PROTOCOL_MISMATCH, "protocol"))
    if left.method.family is JumpHeightEstimatorFamily.TAKEOFF_VELOCITY:
        if (
            left_parameters.takeoff_velocity_sample_convention
            != right_parameters.takeoff_velocity_sample_convention
        ):
            differences.append(
                (ComparabilityReasonCode.METHOD_MISMATCH, "takeoff velocity sample convention")
            )
        if (
            left_parameters.source_velocity_operation != right_parameters.source_velocity_operation
            or left_parameters.source_velocity_integration_method
            != right_parameters.source_velocity_integration_method
        ):
            differences.append(
                (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, "upstream mechanics")
            )
        if (
            left.source_velocity is not None
            and right.source_velocity is not None
            and left.source_velocity.observation.identity.processing.filtering
            != right.source_velocity.observation.identity.processing.filtering
        ):
            differences.append(
                (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, "upstream filtering")
            )
        if _zero_reference_key(left_parameters) != _zero_reference_key(right_parameters):
            differences.append(
                (
                    ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH,
                    "zero-velocity reference",
                )
            )
        if left_parameters.system_contract != right_parameters.system_contract:
            differences.append(
                (ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH, "system contract")
            )
    return tuple(differences)


def _comparability_result(
    request: CMJJumpHeightComparabilityRequest,
    state: ComparabilityState,
    *,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
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
        rule_reference=CMJ_JUMP_HEIGHT_COMPARABILITY_RULE,
        evidence_references=(RES38_DECISION_CLASSIFICATION_COMPARABILITY,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _assert_output_identity(
    observation: ScientificMeasurementObservation,
    method: JumpHeightEstimatorMethod,
    parameters: JumpHeightEstimatorParameters,
) -> None:
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("jump-height observation requires a CMJ measurement identity")
    if identity.semantic.construct.stable_id != CMJ_SUPPORTED_SYSTEM_CONSTRUCT.stable_id:
        raise ValueError("jump-height output must preserve supported-system construct")
    if identity.semantic.measurand.stable_id != CMJ_JUMP_HEIGHT_MEASURAND.stable_id:
        raise ValueError("jump-height output has the wrong measurand")
    if identity.semantic.metric_definition.stable_id != CMJ_JUMP_HEIGHT_METRIC.stable_id:
        raise ValueError("jump-height output has the wrong metric")
    if identity.processing.estimator != method.reference:
        raise ValueError("jump-height output must preserve estimator identity")
    if identity.processing.registered_operation != method.operation:
        raise ValueError("jump-height output must preserve operation identity")
    if identity.version.processing_method != method.operation:
        raise ValueError("jump-height output version must preserve operation identity")
    if identity.version.method_registry_version != CMJ_REGISTRY_VERSION:
        raise ValueError("jump-height output must use the registered CMJ registry version")
    if identity.version.software_version != RES38_SOFTWARE_VERSION:
        raise ValueError("jump-height output must use the registered RES-38 software version")
    if identity.processing.method_parameters is None:
        raise ValueError("jump-height output requires method parameters")
    parameter_map = {entry.key: entry.value for entry in identity.processing.method_parameters}
    if parameter_map.get("estimator_parameters") != canonical_json(parameters):
        raise ValueError("jump-height output must preserve typed estimator parameters")
    if parameter_map.get("output_schema") != CMJ_JUMP_HEIGHT_SCHEMA.stable_id:
        raise ValueError("jump-height output must preserve the registered scalar schema")
    for key in ("filtering", "interpolation", "resampling", "drift_correction"):
        if parameter_map.get(key) != "none":
            raise ValueError(f"jump-height output has unregistered {key} state")
    if parameter_map.get("standard_gravity_substitution") is not False:
        raise ValueError("jump-height output must not substitute standard gravity")
    if observation.result.unit != METER or not isinstance(observation.result.value, ScalarValue):
        raise ValueError("jump-height output must be a scalar in metres")
    if isinstance(observation.result.value.value, bool):
        raise ValueError("jump-height scalar must be numeric")
    value = float(observation.result.value.value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("jump-height scalar must be finite and nonnegative")
    classification = observation.result.classification
    if classification.value_origin is not ValueOrigin.MODEL_ESTIMATE:
        raise ValueError("ballistic jump height must be classified as MODEL_ESTIMATE")
    if classification.scientific_roles != (ScientificRole.PERFORMANCE_OUTCOME,):
        raise ValueError("jump-height output must carry the explicit performance-outcome role")


def _assert_output_run(
    observation: ScientificMeasurementObservation,
    method: JumpHeightEstimatorMethod,
) -> None:
    matching = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(matching) != 1:
        raise ValueError("jump-height output must have exactly one output processing run")
    if matching[0].method != method.operation:
        raise ValueError("jump-height output run method must match estimator operation")
    if matching[0].parameters != observation.identity.processing.method_parameters:
        raise ValueError("jump-height output run parameters must match identity parameters")


def _assert_output_value(
    observation: ScientificMeasurementObservation,
    method: JumpHeightEstimatorMethod,
    parameters: JumpHeightEstimatorParameters,
    source_velocity: SupportedSystemComVelocityResult | None,
) -> None:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        raise ValueError("jump-height output must contain a numeric scalar")
    if method.family is JumpHeightEstimatorFamily.FLIGHT_TIME:
        if parameters.flight_time_s is None:
            raise ValueError("flight-time output must preserve its duration")
        expected = parameters.gravity.value_m_per_s2 * parameters.flight_time_s**2 / 8.0
    elif method.family is JumpHeightEstimatorFamily.TAKEOFF_VELOCITY:
        if source_velocity is None or parameters.takeoff_velocity_m_per_s is None:
            raise ValueError("takeoff-velocity output must preserve its sampled velocity")
        expected = parameters.takeoff_velocity_m_per_s**2 / (
            2.0 * parameters.gravity.value_m_per_s2
        )
    else:
        raise ValueError("unregistered jump-height estimator family")
    if float(value.value) != expected:
        raise ValueError("jump-height scalar does not match its registered equation")


def _assert_event(
    event: CMJEventOccurrence,
    method: object,
    role: str,
) -> None:
    if event.detector_method != method:
        raise ValueError(f"{role} event detector method is not the registered RES-36 method")
    if event.status is not CMJEventOccurrenceStatus.DETECTED:
        raise ValueError(f"{role} event is not a detected occurrence")


def _assert_shared_event_source(
    takeoff: CMJEventOccurrence,
    landing: CMJEventOccurrence,
) -> None:
    if (
        takeoff.source_observation_id != landing.source_observation_id
        or takeoff.source_signal_id != landing.source_signal_id
        or takeoff.source_artifact_id != landing.source_artifact_id
        or takeoff.source_acquisition_id != landing.source_acquisition_id
        or takeoff.source_measurement_identity.identity_id
        != landing.source_measurement_identity.identity_id
        or takeoff.source_timebase != landing.source_timebase
        or takeoff.source_sample_count != landing.source_sample_count
    ):
        raise ValueError("takeoff and landing events must share exact source identity")


def _assert_flight_parameters(
    parameters: JumpHeightEstimatorParameters,
    takeoff: CMJEventOccurrence,
    landing: CMJEventOccurrence,
) -> None:
    if (
        parameters.takeoff_event_id != takeoff.occurrence_id
        or parameters.landing_event_id != landing.occurrence_id
        or parameters.takeoff_sample_index != takeoff.sample_index
        or parameters.landing_sample_index != landing.sample_index
        or parameters.takeoff_event_time_s != takeoff.event_time_s
        or parameters.landing_event_time_s != landing.event_time_s
        or parameters.flight_time_s != landing.event_time_s - takeoff.event_time_s
        or parameters.source_observation_id != takeoff.source_observation_id
        or parameters.source_signal_id != takeoff.source_signal_id
        or parameters.source_artifact_id != takeoff.source_artifact_id
        or parameters.source_acquisition_id != takeoff.source_acquisition_id
        or parameters.source_measurement_identity_id
        != takeoff.source_measurement_identity.identity_id
        or parameters.source_timebase != takeoff.source_timebase
        or landing.sample_index <= takeoff.sample_index
        or landing.event_time_s <= takeoff.event_time_s
    ):
        raise ValueError("flight-time parameters must preserve exact event-time arithmetic")
    if (
        parameters.gravity.reference_type
        is not GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION
    ):
        raise ValueError("flight-time output must use local gravity")


def _assert_velocity_linkage(
    velocity: SupportedSystemComVelocityResult,
    takeoff: CMJEventOccurrence,
    parameters: JumpHeightEstimatorParameters,
    *,
    raise_errors: bool,
) -> None:
    condition = velocity.initial_velocity_condition
    local_index = takeoff.sample_index - velocity.series.sample_start_index
    sampled_takeoff_velocity = (
        velocity.samples[local_index] if 0 <= local_index < len(velocity.samples) else None
    )
    checks = (
        isinstance(condition, QualifiedZeroVelocityReference),
        condition.is_authorized if isinstance(condition, QualifiedZeroVelocityReference) else False,
        takeoff.source_signal_id in velocity.series.source_signal_ids,
        takeoff.source_artifact_id in velocity.series.source_artifact_ids,
        takeoff.source_observation_id in velocity.series.source_observation_ids,
        takeoff.source_measurement_identity.identity_id
        in velocity.series.source_measurement_identity_ids,
        takeoff.source_timebase == velocity.series.timebase,
        takeoff.source_sample_count == velocity.series.source_sample_count,
        takeoff.sample_index in velocity.series.source_sample_indices,
        any(
            acquisition.acquisition_id == takeoff.source_acquisition_id
            for acquisition in velocity.observation.provenance.acquisitions
        ),
        parameters.source_velocity_observation_id == velocity.observation.observation_id,
        parameters.source_velocity_series_id == velocity.series.series_id,
        parameters.source_observation_id == takeoff.source_observation_id,
        parameters.source_signal_id == takeoff.source_signal_id,
        parameters.source_artifact_id == takeoff.source_artifact_id,
        parameters.source_acquisition_id == takeoff.source_acquisition_id,
        parameters.source_measurement_identity_id
        == takeoff.source_measurement_identity.identity_id,
        parameters.source_timebase == takeoff.source_timebase,
        parameters.takeoff_event_id == takeoff.occurrence_id,
        parameters.takeoff_sample_index == takeoff.sample_index,
        parameters.takeoff_event_time_s == takeoff.event_time_s,
        parameters.takeoff_velocity_sample_index == takeoff.sample_index,
        parameters.takeoff_velocity_sample_convention
        == CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
        parameters.takeoff_velocity_m_per_s == sampled_takeoff_velocity,
    )
    if not all(checks) and raise_errors:
        raise ValueError("takeoff event and velocity series linkage is incomplete")
    if (
        parameters.source_velocity_initial_condition != condition
        or parameters.source_velocity_operation != velocity.series.operation
        or parameters.source_velocity_integration_method != velocity.series.integration_method
    ) and raise_errors:
        raise ValueError("velocity method and qualified zero-velocity linkage is incomplete")


def _source_observation_refusal(
    source_observation: ScientificMeasurementObservation | None,
    event: CMJEventOccurrence,
    claim: str,
) -> RefusalResult | None:
    if source_observation is None:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.MISSING_METADATA,),
            ("exact source observation for the event occurrence",),
        )
    if (
        source_observation.observation_id != event.source_observation_id
        or source_observation.identity.identity_id != event.source_measurement_identity.identity_id
        or not any(
            artifact.artifact_id == event.source_artifact_id
            for artifact in source_observation.provenance.source_artifacts
        )
        or not any(
            acquisition.acquisition_id == event.source_acquisition_id
            for acquisition in source_observation.provenance.acquisitions
        )
    ):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("source observation, artifact, acquisition, and measurement identity matching event",),
            observation_ids=(source_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _shared_event_source_refusal(
    takeoff: CMJEventOccurrence,
    landing: CMJEventOccurrence,
    claim: str,
) -> RefusalResult | None:
    try:
        _assert_shared_event_source(takeoff, landing)
    except ValueError:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("takeoff and landing from the same source signal, trial, acquisition, and timebase",),
            observation_ids=(takeoff.source_observation_id, landing.source_observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _velocity_linkage_refusal(
    velocity: SupportedSystemComVelocityResult,
    takeoff: CMJEventOccurrence,
    claim: str,
) -> RefusalResult | None:
    condition = velocity.initial_velocity_condition
    if not isinstance(condition, QualifiedZeroVelocityReference):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,),
            ("QualifiedZeroVelocityReference in velocity result and series",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not condition.is_authorized:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED,),
            ("adjudicated QualifiedZeroVelocityReference",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED,
        )
    if not velocity.system_contract.is_authorized:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED,),
            ("authorized supported-system mechanics contract",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    checks = (
        takeoff.source_signal_id in velocity.series.source_signal_ids,
        takeoff.source_artifact_id in velocity.series.source_artifact_ids,
        takeoff.source_observation_id in velocity.series.source_observation_ids,
        takeoff.source_measurement_identity.identity_id
        in velocity.series.source_measurement_identity_ids,
        takeoff.source_timebase == velocity.series.timebase,
        takeoff.source_sample_count == velocity.series.source_sample_count,
        takeoff.sample_index in velocity.series.source_sample_indices,
        any(
            acquisition.acquisition_id == takeoff.source_acquisition_id
            for acquisition in velocity.observation.provenance.acquisitions
        ),
    )
    if not all(checks):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("takeoff event source and sample inside the exact velocity mechanics chain",),
            observation_ids=(velocity.observation.observation_id, takeoff.source_observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _velocity_gravity_refusal(
    velocity: SupportedSystemComVelocityResult,
    gravity: GravityReference,
    claim: str,
) -> RefusalResult | None:
    mass_runs = tuple(
        run
        for run in velocity.observation.provenance.processing_runs
        if run.method.stable_id == CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT.stable_id
        and run.output_entity_id in velocity.series.source_observation_ids
    )
    if len(mass_runs) != 1:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_MISSING,),
            ("one physical-system-mass processing run with explicit local gravity",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = {entry.key: entry.value for entry in mass_runs[0].parameters}
    if (
        parameters.get("gravity_value_m_per_s2") != gravity.value_m_per_s2
        or parameters.get("gravity_reference_type") != gravity.reference_type.value
        or parameters.get("gravity_source") != gravity.source.stable_id
    ):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH,),
            ("estimator gravity equal to the physical mass/acceleration chain gravity",),
            observation_ids=(velocity.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _gravity_refusal(
    gravity: GravityReference | None,
    claim: str,
) -> RefusalResult | None:
    if gravity is None:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_MISSING,),
            ("explicit local GravityReference",),
        )
    if not isinstance(gravity, GravityReference):
        return _jump_refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_INVALID,),
            ("registered GravityReference",),
        )
    if gravity.reference_type is not GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH,),
            ("local gravitational acceleration; standard gravity is not this V1 method",),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    return None


def _event_refusal_if_invalid(
    event: CMJEventOccurrence,
    expected_method: object,
    role: str,
    claim: str,
) -> RefusalResult | None:
    if event.detector_method != expected_method:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            (f"registered {role} detector method",),
            observation_ids=(event.source_observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if event.status is not CMJEventOccurrenceStatus.DETECTED:
        return _jump_refusal(
            claim,
            (RefusalReasonCode.EVENT_DEFINITION_MISMATCH,),
            (f"detected {role} event occurrence",),
            observation_ids=(event.source_observation_id,),
        )
    return None


def _assert_event_source_identity(event: CMJEventOccurrence) -> None:
    if event.source_signal_id.instance_type != "signal":
        raise ValueError("event source signal must identify a signal")


def _event_method_key(event: CMJEventOccurrence) -> tuple[object, ...]:
    return (
        event.definition.reference.stable_id,
        event.detector_method.reference.stable_id,
        canonical_json(event.detector_parameters),
    )


def _protocol_key(identity: object) -> str:
    if not isinstance(identity, CMJMeasurementIdentity):
        return "missing"
    return canonical_json(identity.semantic.protocol_identity)


def _zero_reference_key(parameters: JumpHeightEstimatorParameters) -> str:
    condition = parameters.source_velocity_initial_condition
    if condition is None:
        return "missing"
    segment = condition.weighing_segment
    return repr(
        (
            condition.method.stable_id,
            condition.evidence_decision.stable_id,
            condition.value_m_per_s,
            condition.unit.identifier.stable_id,
            segment.selection_method.stable_id,
            segment.start_index,
            segment.end_index,
            tuple((entry.key, entry.value) for entry in segment.selection_parameters),
            canonical_json(condition.weighing_qc),
        )
    )


def _append_unique[T](values: tuple[T, ...], additions: tuple[T, ...]) -> tuple[T, ...]:
    result = list(values)
    for addition in additions:
        if addition not in result:
            result.append(addition)
    return tuple(result)


def _append_edge(edges: list[LineageEdge], edge: LineageEdge) -> None:
    if edge not in edges:
        edges.append(edge)


def _unique(values: tuple[InstanceIdentifier, ...]) -> tuple[InstanceIdentifier, ...]:
    return _append_unique((), values)


def _qualified(value: InstanceIdentifier) -> str:
    return value.qualified


def _nonnegative_index(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")


def _finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _jump_refusal(
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    reason_values = tuple(reason.value for reason in reason_codes)
    key = canonical_hash(
        {
            "mission": "RES38",
            "blocked_claim": blocked_claim,
            "reason_codes": reason_values,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res38-jump-height:{key}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=reason_values,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "each valid event or mechanics result remains independently describable",
            "no unqualified generic jump-height or athlete-COM claim is emitted",
        ),
        observation_ids=observation_ids,
    )


__all__ = [
    "CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD",
    "CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD",
    "JUMP_HEIGHT_ESTIMAND",
    "RES38_SOFTWARE_VERSION",
    "CMJJumpHeightComparabilityRequest",
    "CMJJumpHeightResult",
    "JumpHeightEstimate",
    "JumpHeightEstimatorFamily",
    "JumpHeightEstimatorMethod",
    "JumpHeightEstimatorParameters",
    "TakeoffVelocitySampleConvention",
    "assess_cmj_jump_height_comparability",
    "compare_cmj_jump_height_estimates",
    "defer_com_displacement_jump_height",
    "estimate_flight_time_jump_height",
    "estimate_takeoff_velocity_jump_height",
    "refusal_for_cmj_jump_height_comparability",
    "refuse_unregistered_cmj_jump_height_estimator",
]
