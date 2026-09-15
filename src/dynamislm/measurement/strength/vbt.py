"""Deterministic squat/bench VBT measurements and strength-model boundaries."""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import pairwise

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    UnitReference,
    VersionIdentity,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_tuple_items,
    require_tuple,
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
from dynamislm.measurement.strength.identity import (
    StrengthAcquisitionIdentity,
    StrengthArtifactHashScope,
    StrengthArtifactStatus,
    StrengthEquipmentMode,
    StrengthExternalLoadStatus,
    StrengthHashAlgorithm,
    StrengthLoadIdentity,
    StrengthLoadSemantics,
    StrengthProcessingComponentStatus,
    StrengthProcessingIdentity,
    StrengthProcessingState,
    StrengthProtocolIdentity,
    StrengthSensorModality,
    StrengthSourceArtifact,
    StrengthTestFamily,
    StrengthTimebase,
    StrengthTimebaseKind,
    VBTMeasurementIdentity,
    canonical_series_digest,
    time_at,
    validate_series_timebase,
)
from dynamislm.measurement.strength.registry import (
    BENCH_PRESS_VBT_TEST_FAMILY,
    KILOGRAM,
    METER_PER_SECOND,
    PERCENT,
    RES66_DECISION_STRENGTH_IMTP_VBT,
    SQUAT_VBT_TEST_FAMILY,
    STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT,
    STRENGTH_REGISTRY_VERSION,
    VBT_BAR_VELOCITY_CONSTRUCT,
    VBT_BEST_PREVIOUS_REPETITION_REFERENCE,
    VBT_CONCENTRIC_PHASE_DEFINITION,
    VBT_ESTIMATED_1RM_MEASURAND,
    VBT_ESTIMATED_1RM_METRIC,
    VBT_ESTIMATED_1RM_OPERATION,
    VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD,
    VBT_FASTEST_REPETITION_REFERENCE,
    VBT_FIRST_REPETITION_REFERENCE,
    VBT_FIXED_LOAD_COMPARABILITY_RULE,
    VBT_INPUT_OPERATION,
    VBT_LINEAR_REGRESSION_METHOD,
    VBT_LOAD_VELOCITY_MODEL,
    VBT_MEAN_CONCENTRIC_VELOCITY_METRIC,
    VBT_MEAN_CONCENTRIC_VELOCITY_OPERATION,
    VBT_MEASURED_1RM_MEASURAND,
    VBT_MEASURED_1RM_METRIC,
    VBT_MEASURED_1RM_OPERATION,
    VBT_MEASURED_1RM_SELECTION_RULE,
    VBT_PEAK_VELOCITY_METRIC,
    VBT_PEAK_VELOCITY_OPERATION,
    VBT_PHASE_BOUNDARY_CONVENTION,
    VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY,
    VBT_SUCCESSFUL_REPETITION_CRITERION,
    VBT_VELOCITY_LOSS_MEASURAND,
    VBT_VELOCITY_LOSS_METRIC,
    VBT_VELOCITY_LOSS_OPERATION,
    VBT_VELOCITY_MEASURAND,
    VBT_VELOCITY_SERIES_METRIC,
    VBT_VELOCITY_SERIES_SCHEMA,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES66_SOFTWARE_VERSION = "dynamislm-res66-1.0.0"


class VBTMetric(StrEnum):
    MEAN_CONCENTRIC_VELOCITY = "MEAN_CONCENTRIC_VELOCITY"
    MEAN_PROPULSIVE_VELOCITY = "MEAN_PROPULSIVE_VELOCITY"
    PEAK_VELOCITY = "PEAK_VELOCITY"


class VBTPhaseAuthorityStatus(StrEnum):
    QUALIFIED_UPSTREAM_EXPLICIT_PHASE_REQUIRED = "QUALIFIED_UPSTREAM_EXPLICIT_PHASE_REQUIRED"


class VBTVelocityLossReference(StrEnum):
    FIRST_REPETITION = "FIRST_REPETITION"
    FASTEST_REPETITION = "FASTEST_REPETITION"
    BEST_PREVIOUS_REPETITION = "BEST_PREVIOUS_REPETITION"


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _numeric_scalar(observation: ScientificMeasurementObservation) -> float:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        raise ValueError("observation must contain a numeric scalar")
    return _finite(value.value, "observation scalar")


def _refusal(
    claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
    safe_descriptions: tuple[str, ...] = (
        "the qualified VBT source series remains independently describable",
        "no unsupported measured-strength, fatigue, readiness, or physiological claim is emitted",
    ),
) -> RefusalResult:
    codes = tuple(code.value for code in reason_codes)
    digest = canonical_hash(
        {
            "claim": claim,
            "reason_codes": codes,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res66-vbt:{digest}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions,
        evidence_references=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        observation_ids=observation_ids,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTVelocitySeries:
    """Exact delivered velocity samples for one repetition."""

    series_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    samples: tuple[float, ...]
    timebase: StrengthTimebase
    unit: UnitReference
    physical_axis: RegistryReference | None = None
    reference_frame: RegistryReference | None = None
    sign_convention: SignConvention | None = None
    processing_state: StrengthProcessingState = StrengthProcessingState.PROVIDER_PROCESSED

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("series_id", self.series_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("acquisition_id", self.acquisition_id, "acquisition"),
        ):
            if value.instance_type != expected:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("source_measurement_identity_id must identify a measurement")
        require_tuple(self.samples, "samples")
        if not self.samples:
            raise ValueError("VBT velocity series must contain samples")
        object.__setattr__(
            self, "samples", tuple(_finite(value, "velocity sample") for value in self.samples)
        )
        _require_instance(self.timebase, StrengthTimebase, "timebase")
        validate_series_timebase(self.timebase, len(self.samples))
        if self.unit != METER_PER_SECOND:
            raise ValueError("VBT velocity series must use m/s")
        _require_optional_instance(self.physical_axis, RegistryReference, "physical_axis")
        _require_optional_instance(self.reference_frame, RegistryReference, "reference_frame")
        _require_optional_instance(self.sign_convention, SignConvention, "sign_convention")
        _require_enum(self.processing_state, StrengthProcessingState, "processing_state")
        if self.processing_state in {
            StrengthProcessingState.UNKNOWN,
            StrengthProcessingState.DYNAMISLM_PROCESSED,
        }:
            raise ValueError("VBT source series must be raw or provider/device processed")

    def canonical_content_digest(self) -> str:
        return canonical_series_digest(self.samples, self.timebase, unit=self.unit)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTConcentricPhase:
    """Qualified upstream phase support; no phase is inferred from a scalar."""

    phase_id: InstanceIdentifier
    source_context: ObservationContext
    source_observation_id: InstanceIdentifier
    source_series_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_timebase: StrengthTimebase
    source_sample_count: int
    set_id: InstanceIdentifier
    rep_id: InstanceIdentifier
    rep_index: int
    external_load: StrengthLoadIdentity
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float
    phase_definition: RegistryReference = VBT_CONCENTRIC_PHASE_DEFINITION
    boundary_method: RegistryReference = VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD
    boundary_convention: RegistryReference = VBT_PHASE_BOUNDARY_CONVENTION
    boundary_parameters: tuple[MetadataEntry, ...] = ()
    processing_run_id: InstanceIdentifier | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if self.phase_id.instance_type != "phase-occurrence":
            raise ValueError("phase_id must identify a phase occurrence")
        for field_name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_series_id", self.source_series_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
            ("set_id", self.set_id, "set"),
            ("rep_id", self.rep_id, "rep"),
        ):
            if value.instance_type != expected:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("phase source identity must identify a measurement")
        _require_instance(self.source_timebase, StrengthTimebase, "source_timebase")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("phase source_sample_count must be positive")
        if type(self.rep_index) is not int or self.rep_index < 1:
            raise ValueError("rep_index must be a positive integer")
        if (
            type(self.start_index) is not int
            or type(self.end_index) is not int
            or self.start_index < 0
            or self.end_index <= self.start_index
        ):
            raise ValueError(
                "concentric phase must contain an inclusive interval with at least two samples"
            )
        _require_instance(self.external_load, StrengthLoadIdentity, "external_load")
        _require_instance(self.phase_definition, RegistryReference, "phase_definition")
        _require_instance(self.boundary_method, RegistryReference, "boundary_method")
        _require_instance(self.boundary_convention, RegistryReference, "boundary_convention")
        _require_tuple_items(self.boundary_parameters, MetadataEntry, "boundary_parameters")
        _finite(self.start_time_s, "phase start time")
        _finite(self.end_time_s, "phase end time")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("phase duration must be positive")
        if self.processing_run_id is not None:
            if self.processing_run_id.instance_type != "processing-run":
                raise ValueError("phase processing_run_id must identify a processing run")
            if self.provenance is None:
                raise ValueError("phase processing_run_id requires provenance")
            matching = tuple(
                run
                for run in self.provenance.processing_runs
                if run.output_entity_id == self.phase_id
            )
            if len(matching) != 1 or matching[0].processing_run_id != self.processing_run_id:
                raise ValueError("phase must preserve one producing processing run")
            if matching[0].method != self.boundary_method:
                raise ValueError("phase producing run method does not match boundary method")
        elif self.provenance is not None:
            raise ValueError("phase provenance requires processing_run_id")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTVelocitySeriesEvidence:
    """Set/rep-bound VBT evidence retaining the delivered series and source digest."""

    observation: ScientificMeasurementObservation
    identity: VBTMeasurementIdentity
    series: VBTVelocitySeries
    source_artifact: StrengthSourceArtifact
    acquisition: AcquisitionRecord
    set_id: InstanceIdentifier
    rep_id: InstanceIdentifier
    rep_index: int
    external_load: StrengthLoadIdentity
    source_series_digest: str
    phase: VBTConcentricPhase | None = None

    def __post_init__(self) -> None:
        _validate_vbt_evidence(self)

    @property
    def series_id(self) -> InstanceIdentifier:
        return self.series.series_id

    @property
    def bound_observation_id(self) -> InstanceIdentifier:
        return self.observation.observation_id

    @property
    def source_processing_state(self) -> StrengthProcessingState:
        return self.series.processing_state

    def with_phase(self, phase: VBTConcentricPhase) -> VBTVelocitySeriesEvidence:
        _validate_phase_for_evidence(self, phase)
        return replace(self, phase=phase)


def source_artifact_for_vbt_series(
    series: VBTVelocitySeries,
    *,
    media_type: str = "application/vnd.dynamislm.vbt.velocity-series",
) -> StrengthSourceArtifact:
    return StrengthSourceArtifact(
        artifact_id=series.source_artifact_id,
        content_digest=series.canonical_content_digest(),
        media_type=media_type,
        immutable=True,
        hash_algorithm=StrengthHashAlgorithm.SHA256,
        hash_scope=StrengthArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
        status=StrengthArtifactStatus.VERIFIED,
    )


def _source_origin(processing_state: StrengthProcessingState) -> ValueOrigin:
    if processing_state is StrengthProcessingState.RAW_ACQUIRED:
        return ValueOrigin.DIRECT_MEASUREMENT
    if processing_state in {
        StrengthProcessingState.DEVICE_PROCESSED,
        StrengthProcessingState.PROVIDER_PROCESSED,
    }:
        return ValueOrigin.PROVIDER_DERIVED
    raise ValueError("unresolved VBT source processing state")


def create_vbt_velocity_evidence(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    identity: VBTMeasurementIdentity,
    series: VBTVelocitySeries,
    source_artifact: StrengthSourceArtifact,
    acquisition: AcquisitionRecord,
    set_id: InstanceIdentifier,
    rep_id: InstanceIdentifier,
    rep_index: int,
    external_load: StrengthLoadIdentity,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> VBTVelocitySeriesEvidence:
    if observation_id.instance_type != "observation":
        raise ValueError("VBT observation_id must identify an observation")
    _validate_vbt_identity(identity)
    if (
        source_artifact.artifact_id != series.source_artifact_id
        or source_artifact.content_digest != series.canonical_content_digest()
    ):
        raise ValueError("VBT source artifact does not match the delivered series")
    if (
        source_artifact.status is not StrengthArtifactStatus.VERIFIED
        or not source_artifact.immutable
    ):
        raise ValueError("VBT source artifact must be immutable and verified")
    if identity.identity_id != series.source_measurement_identity_id:
        raise ValueError("VBT series identity does not match measurement identity")
    if (
        identity.acquisition.raw_artifact != source_artifact.artifact_id
        or identity.acquisition.acquisition_instance_id != acquisition.acquisition_id
    ):
        raise ValueError("VBT acquisition identity does not match source objects")
    if identity.acquisition.timebase != series.timebase or identity.acquisition.unit != series.unit:
        raise ValueError("VBT acquisition identity does not preserve series timebase/unit")
    if identity.acquisition.processing_state != series.processing_state:
        raise ValueError("VBT acquisition processing state does not match series")
    if (
        acquisition.source_artifact_id != source_artifact.artifact_id
        or acquisition.acquisition_id != series.acquisition_id
    ):
        raise ValueError("VBT acquisition record does not match source series")
    if acquisition.sensor_channel != identity.acquisition.sensor_channel:
        raise ValueError("VBT acquisition channel does not match identity")
    if (
        set_id.instance_type != "set"
        or rep_id.instance_type != "rep"
        or type(rep_index) is not int
        or rep_index < 1
    ):
        raise ValueError("VBT evidence requires typed set/rep IDs and a positive rep index")
    protocol = identity.semantic.protocol_identity
    if (
        protocol is not None
        and protocol.external_load_status.name == "DEFINED"
        and protocol.external_load != external_load
    ):
        raise ValueError("VBT evidence load does not match protocol load identity")
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", observation_id.value),
        source_artifacts=(source_artifact,),
        acquisitions=(acquisition,),
        processing_runs=(),
        lineage_edges=(
            LineageEdge(
                source_artifact.artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                LineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
            LineageEdge(
                series.series_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
        evidence_references=evidence_references,
        recorded_at=recorded_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=StructuredOutputReference(
                artifact_id=source_artifact.artifact_id, schema=VBT_VELOCITY_SERIES_SCHEMA
            ),
            unit=series.unit,
            classification=ScientificClassification(_source_origin(series.processing_state), ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return VBTVelocitySeriesEvidence(
        observation=observation,
        identity=identity,
        series=series,
        source_artifact=source_artifact,
        acquisition=acquisition,
        set_id=set_id,
        rep_id=rep_id,
        rep_index=rep_index,
        external_load=external_load,
        source_series_digest=series.canonical_content_digest(),
    )


def _validate_vbt_identity(identity: VBTMeasurementIdentity) -> None:
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("VBT operation requires VBTMeasurementIdentity")
    if identity.semantic.test_family not in {
        SQUAT_VBT_TEST_FAMILY,
        BENCH_PRESS_VBT_TEST_FAMILY,
    }:
        raise ValueError("VBT identity must use squat or bench-press VBT test family")
    protocol = identity.semantic.protocol_identity
    if protocol is None or identity.semantic.protocol is None:
        raise ValueError("complete VBT protocol identity is required")
    if protocol.test_family not in {
        StrengthTestFamily.SQUAT_VBT,
        StrengthTestFamily.BENCH_PRESS_VBT,
    }:
        raise ValueError("VBT protocol must use squat or bench-press VBT family")


def _validate_vbt_evidence(evidence: VBTVelocitySeriesEvidence) -> None:
    _validate_vbt_identity(evidence.identity)
    if evidence.observation.identity != evidence.identity:
        raise ValueError("VBT observation and supplied identity differ")
    series = evidence.series
    artifact = evidence.source_artifact
    acquisition = evidence.acquisition
    identity = evidence.identity
    if identity.processing.registered_operation != VBT_INPUT_OPERATION:
        raise ValueError("VBT source operation is not registered")
    if identity.version.processing_method != VBT_INPUT_OPERATION:
        raise ValueError("VBT source version does not name its registered operation")
    if identity.semantic.metric_definition != VBT_VELOCITY_SERIES_METRIC:
        raise ValueError("VBT source metric identity must be the delivered velocity series")
    if (
        identity.semantic.construct != VBT_BAR_VELOCITY_CONSTRUCT
        or identity.semantic.measurand != VBT_VELOCITY_MEASURAND
    ):
        raise ValueError("VBT source semantic identity is not the bar-velocity series")
    protocol = identity.semantic.protocol_identity
    if protocol is None:
        raise ValueError("VBT protocol identity is unresolved")
    if (
        protocol.device_or_system is not None
        and protocol.device_or_system != identity.acquisition.device
    ):
        raise ValueError("VBT protocol device does not match acquisition device")
    if protocol.provider is not None and protocol.provider != identity.acquisition.provider:
        raise ValueError("VBT protocol provider does not match acquisition provider")
    if (
        protocol.sensor_modality is not StrengthSensorModality.UNKNOWN
        and protocol.sensor_modality != identity.acquisition.sensor_modality
    ):
        raise ValueError("VBT protocol sensor modality does not match acquisition")
    if (
        protocol.attachment_location is not None
        and protocol.attachment_location != identity.acquisition.attachment_location
    ):
        raise ValueError("VBT protocol attachment does not match acquisition")
    if protocol.sampling is not None and protocol.sampling != identity.acquisition.sampling:
        raise ValueError("VBT protocol sampling does not match acquisition")
    if series.source_measurement_identity_id != identity.identity_id:
        raise ValueError("VBT series source identity does not match evidence identity")
    if artifact.artifact_id != series.source_artifact_id:
        raise ValueError("VBT artifact does not match series")
    if artifact.content_digest != series.canonical_content_digest():
        raise ValueError("VBT source-series digest does not reproduce")
    if evidence.source_series_digest != series.canonical_content_digest():
        raise ValueError("VBT evidence source-series digest is stale")
    if not artifact.immutable or artifact.status is not StrengthArtifactStatus.VERIFIED:
        raise ValueError("VBT source artifact must be immutable and verified")
    if identity.acquisition.raw_artifact != artifact.artifact_id:
        raise ValueError("VBT acquisition identity does not preserve source artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("VBT acquisition identity does not preserve acquisition")
    if (
        acquisition.source_artifact_id != artifact.artifact_id
        or acquisition.acquisition_id != series.acquisition_id
    ):
        raise ValueError("VBT acquisition record is not bound to the series")
    if identity.acquisition.timebase != series.timebase or identity.acquisition.unit != series.unit:
        raise ValueError("VBT acquisition identity does not preserve timebase/unit")
    if (
        identity.acquisition.physical_axis != series.physical_axis
        or identity.acquisition.reference_frame != series.reference_frame
        or identity.acquisition.sign_convention != series.sign_convention
    ):
        raise ValueError("VBT acquisition identity does not preserve axis/frame/sign")
    if identity.acquisition.processing_state != series.processing_state:
        raise ValueError("VBT acquisition processing state does not match series")
    if identity.processing.processing_state != series.processing_state:
        raise ValueError("VBT processing identity state does not match series")
    if identity.acquisition.sampling is None:
        raise ValueError("VBT source sampling metadata is required")
    if (
        series.timebase.kind is StrengthTimebaseKind.REGULAR
        and identity.acquisition.sampling.frequency_hz is not None
        and identity.acquisition.sampling.frequency_hz != series.timebase.sample_rate_hz
    ):
        raise ValueError("VBT sampling frequency does not match regular timebase")
    if acquisition.device != identity.acquisition.device:
        raise ValueError("VBT acquisition device does not match identity")
    if acquisition.sampling != identity.acquisition.sampling:
        raise ValueError("VBT acquisition sampling does not match identity")
    if acquisition.sensor_channel != identity.acquisition.sensor_channel:
        raise ValueError("VBT acquisition channel does not match identity")
    if evidence.observation.result.status is not ResultStatus.VALID:
        raise ValueError("VBT source observation is not valid")
    source_value = evidence.observation.result.value
    if (
        not isinstance(source_value, StructuredOutputReference)
        or source_value.artifact_id != artifact.artifact_id
        or source_value.schema != VBT_VELOCITY_SERIES_SCHEMA
    ):
        raise ValueError("VBT source result does not reference the exact velocity series")
    if evidence.observation.result.classification.value_origin != _source_origin(
        series.processing_state
    ):
        raise ValueError("VBT source value origin does not match processing state")
    if evidence.set_id.instance_type != "set" or evidence.rep_id.instance_type != "rep":
        raise ValueError("VBT evidence requires typed set and rep identifiers")
    if type(evidence.rep_index) is not int or evidence.rep_index < 1:
        raise ValueError("VBT rep_index must be a positive integer")
    _require_instance(evidence.external_load, StrengthLoadIdentity, "external_load")
    protocol = identity.semantic.protocol_identity
    if (
        protocol is not None
        and protocol.external_load_status.name == "DEFINED"
        and protocol.external_load != evidence.external_load
    ):
        raise ValueError("VBT evidence load does not equal protocol load")
    provenance = evidence.observation.provenance
    if artifact.artifact_id not in tuple(item.artifact_id for item in provenance.source_artifacts):
        raise ValueError("VBT provenance omits source artifact")
    if acquisition.acquisition_id not in tuple(
        item.acquisition_id for item in provenance.acquisitions
    ):
        raise ValueError("VBT provenance omits source acquisition")
    matching_artifacts = tuple(
        item for item in provenance.source_artifacts if item.artifact_id == artifact.artifact_id
    )
    matching_acquisitions = tuple(
        item
        for item in provenance.acquisitions
        if item.acquisition_id == acquisition.acquisition_id
    )
    if matching_artifacts != (artifact,) or matching_acquisitions != (acquisition,):
        raise ValueError("VBT provenance objects do not match bound inputs")
    if not any(
        edge.from_id == artifact.artifact_id.qualified
        and edge.to_id == acquisition.acquisition_id.qualified
        and edge.relation is LineageRelation.ACQUIRED_AS
        for edge in provenance.lineage_edges
    ) or not any(
        edge.from_id == acquisition.acquisition_id.qualified
        and edge.to_id == evidence.observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in provenance.lineage_edges
    ):
        raise ValueError("VBT provenance omits source artifact/acquisition path")
    if not any(
        edge.from_id == series.series_id.qualified
        and edge.to_id == evidence.observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in provenance.lineage_edges
    ):
        raise ValueError("VBT provenance omits source-series path")
    if evidence.phase is not None:
        _validate_phase_for_evidence(evidence, evidence.phase)


def _phase_parameters(
    evidence: VBTVelocitySeriesEvidence,
    start_index: int,
    end_index: int,
    boundary_parameters: tuple[MetadataEntry, ...],
) -> tuple[MetadataEntry, ...]:
    phase = VBT_CONCENTRIC_PHASE_DEFINITION
    return (
        MetadataEntry("phase_definition", phase.stable_id),
        MetadataEntry("boundary_method", VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD.stable_id),
        MetadataEntry("boundary_convention", VBT_PHASE_BOUNDARY_CONVENTION.stable_id),
        MetadataEntry("source_observation_id", evidence.observation.observation_id.qualified),
        MetadataEntry("source_series_id", evidence.series.series_id.qualified),
        MetadataEntry("source_artifact_id", evidence.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", evidence.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", evidence.identity.identity_id.stable_id),
        MetadataEntry("source_timebase", canonical_json(evidence.series.timebase)),
        MetadataEntry("source_sample_count", len(evidence.series.samples)),
        MetadataEntry("set_id", evidence.set_id.qualified),
        MetadataEntry("rep_id", evidence.rep_id.qualified),
        MetadataEntry("rep_index", evidence.rep_index),
        MetadataEntry("external_load", canonical_json(evidence.external_load)),
        MetadataEntry("start_index", start_index),
        MetadataEntry("end_index", end_index),
        MetadataEntry("start_time_s", time_at(evidence.series.timebase, start_index)),
        MetadataEntry("end_time_s", time_at(evidence.series.timebase, end_index)),
        MetadataEntry("boundary_parameters", canonical_json(boundary_parameters)),
    )


def _validate_phase_for_evidence(
    evidence: VBTVelocitySeriesEvidence,
    phase: VBTConcentricPhase,
) -> None:
    if not isinstance(phase, VBTConcentricPhase):
        raise ValueError("VBT metric requires a qualified VBTConcentricPhase")
    if (
        phase.source_context != evidence.observation.context
        or phase.source_observation_id != evidence.observation.observation_id
        or phase.source_series_id != evidence.series.series_id
        or phase.source_artifact_id != evidence.source_artifact.artifact_id
        or phase.source_acquisition_id != evidence.acquisition.acquisition_id
        or phase.source_measurement_identity_id != evidence.identity.identity_id
        or phase.source_timebase != evidence.series.timebase
        or phase.source_sample_count != len(evidence.series.samples)
        or phase.set_id != evidence.set_id
        or phase.rep_id != evidence.rep_id
        or phase.rep_index != evidence.rep_index
        or phase.external_load != evidence.external_load
    ):
        raise ValueError("VBT phase is not from the exact set/rep/load source")
    if phase.start_index < 0 or phase.end_index >= len(evidence.series.samples):
        raise ValueError("VBT phase exceeds source series")
    if phase.start_index >= phase.end_index:
        raise ValueError("VBT phase requires at least one interval")
    if phase.start_time_s != time_at(
        evidence.series.timebase, phase.start_index
    ) or phase.end_time_s != time_at(evidence.series.timebase, phase.end_index):
        raise ValueError("VBT phase times do not match source timebase")
    if phase.processing_run_id is None or phase.provenance is None:
        raise ValueError("VBT phase must preserve its producing processing run")
    parameters = _phase_parameters(
        evidence, phase.start_index, phase.end_index, phase.boundary_parameters
    )
    runs = tuple(
        run for run in phase.provenance.processing_runs if run.output_entity_id == phase.phase_id
    )
    if (
        len(runs) != 1
        or runs[0].processing_run_id != phase.processing_run_id
        or runs[0].method != VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD
        or runs[0].parameters != parameters
    ):
        raise ValueError("VBT phase processing run does not preserve exact phase fields")
    run = runs[0]
    if phase.source_artifact_id not in run.source_artifact_ids:
        raise ValueError("VBT phase processing run omits source artifact")
    phase_artifacts = tuple(
        artifact
        for artifact in phase.provenance.source_artifacts
        if artifact.artifact_id == evidence.source_artifact.artifact_id
    )
    phase_acquisitions = tuple(
        acquisition
        for acquisition in phase.provenance.acquisitions
        if acquisition.acquisition_id == evidence.acquisition.acquisition_id
    )
    if phase_artifacts != (evidence.source_artifact,) or phase_acquisitions != (
        evidence.acquisition,
    ):
        raise ValueError("VBT phase provenance omits source artifact or acquisition")
    phase_source_entities = (
        phase.source_observation_id,
        phase.source_series_id,
        phase.set_id,
        phase.rep_id,
    )
    for entity_id in phase_source_entities:
        if not any(
            edge.from_id == entity_id.qualified
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in phase.provenance.lineage_edges
        ):
            raise ValueError("VBT phase provenance omits a phase source lineage edge")


def _merge_provenance(left: Provenance, right: Provenance) -> Provenance:
    def unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
        result: list[T] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    return Provenance(
        provenance_id=left.provenance_id,
        source_artifacts=tuple(
            sorted(
                unique((*left.source_artifacts, *right.source_artifacts)),
                key=lambda item: item.artifact_id.qualified,
            )
        ),
        acquisitions=tuple(
            sorted(
                unique((*left.acquisitions, *right.acquisitions)),
                key=lambda item: item.acquisition_id.qualified,
            )
        ),
        processing_runs=tuple(
            sorted(
                unique((*left.processing_runs, *right.processing_runs)),
                key=lambda item: item.processing_run_id.qualified,
            )
        ),
        lineage_edges=tuple(
            sorted(
                unique((*left.lineage_edges, *right.lineage_edges)),
                key=lambda item: (item.from_id, item.to_id, item.relation.value),
            )
        ),
        evidence_references=unique((*left.evidence_references, *right.evidence_references)),
        metrological_traceability=unique(
            (*left.metrological_traceability, *right.metrological_traceability)
        ),
        recorded_at=left.recorded_at or right.recorded_at,
    )


def _provenance_with_run(
    base: Provenance,
    *,
    processing_run: ProcessingRun,
    output_entity_id: InstanceIdentifier,
    source_observation_ids: tuple[InstanceIdentifier, ...],
    source_acquisition_ids: tuple[InstanceIdentifier, ...],
    supported_by: tuple[RegistryReference, ...] = (),
    output_artifacts: tuple[SourceArtifact, ...] = (),
) -> Provenance:
    def unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
        result: list[T] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    artifacts = unique((*base.source_artifacts, *output_artifacts))
    runs = unique((*base.processing_runs, processing_run))
    edges = list(base.lineage_edges)
    for source_id in source_observation_ids:
        edge = LineageEdge(
            source_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for artifact_id in processing_run.source_artifact_ids:
        edge = LineageEdge(
            artifact_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for acquisition_id in source_acquisition_ids:
        edge = LineageEdge(
            acquisition_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    for artifact in output_artifacts:
        edge = LineageEdge(
            processing_run.processing_run_id.qualified,
            artifact.artifact_id.qualified,
            LineageRelation.PRODUCED,
        )
        if edge not in edges:
            edges.append(edge)
    for reference in supported_by:
        edge = LineageEdge(
            reference.stable_id,
            processing_run.processing_run_id.qualified,
            LineageRelation.SUPPORTED_BY,
        )
        if edge not in edges:
            edges.append(edge)
    output_edge = LineageEdge(
        processing_run.processing_run_id.qualified,
        output_entity_id.qualified,
        LineageRelation.PRODUCED,
    )
    if output_edge not in edges:
        edges.append(output_edge)
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_entity_id.value),
        source_artifacts=artifacts,
        acquisitions=base.acquisitions,
        processing_runs=runs,
        lineage_edges=tuple(edges),
        evidence_references=base.evidence_references,
        metrological_traceability=base.metrological_traceability,
        recorded_at=base.recorded_at,
    )


def qualify_vbt_concentric_phase(
    evidence: VBTVelocitySeriesEvidence,
    *,
    start_index: int,
    end_index: int,
    boundary_parameters: tuple[MetadataEntry, ...] = (),
    output_phase_id: InstanceIdentifier | None = None,
) -> VBTConcentricPhase | RefusalResult:
    """Bind explicit upstream phase boundaries without inferring them."""

    claim = "qualify VBT concentric phase support"
    try:
        _validate_vbt_evidence(evidence)
        if type(start_index) is not int or type(end_index) is not int:
            raise ValueError("phase indices must be integers")
        if start_index < 0 or end_index <= start_index or end_index >= len(evidence.series.samples):
            raise ValueError("phase must be an inclusive source interval with at least two samples")
        _require_tuple_items(boundary_parameters, MetadataEntry, "boundary_parameters")
        start_time = time_at(evidence.series.timebase, start_index)
        end_time = time_at(evidence.series.timebase, end_index)
        parameters = _phase_parameters(evidence, start_index, end_index, boundary_parameters)
    except (IndexError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            (f"qualified explicit phase boundaries: {exc}",),
            (evidence.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    digest = canonical_hash(
        {"method": VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD, "parameters": parameters}
    ).removeprefix("sha256:")[:24]
    phase_id = output_phase_id or InstanceIdentifier("phase-occurrence", f"vbt-concentric:{digest}")
    if phase_id.instance_type != "phase-occurrence":
        return _refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            ("output_phase_id must identify a phase occurrence",),
            (evidence.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"vbt-concentric:{digest}"),
        source_artifact_ids=(evidence.source_artifact.artifact_id,),
        method=VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=phase_id,
    )
    provenance = _provenance_with_run(
        evidence.observation.provenance,
        processing_run=run,
        output_entity_id=phase_id,
        source_observation_ids=(evidence.observation.observation_id,),
        source_acquisition_ids=(evidence.acquisition.acquisition_id,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    phase_edges = list(provenance.lineage_edges)
    for entity_id in (evidence.series.series_id, evidence.set_id, evidence.rep_id):
        edge = LineageEdge(
            entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in phase_edges:
            phase_edges.append(edge)
    provenance = replace(provenance, lineage_edges=tuple(phase_edges))
    try:
        return VBTConcentricPhase(
            phase_id=phase_id,
            source_context=evidence.observation.context,
            source_observation_id=evidence.observation.observation_id,
            source_series_id=evidence.series.series_id,
            source_artifact_id=evidence.source_artifact.artifact_id,
            source_acquisition_id=evidence.acquisition.acquisition_id,
            source_measurement_identity_id=evidence.identity.identity_id,
            source_timebase=evidence.series.timebase,
            source_sample_count=len(evidence.series.samples),
            set_id=evidence.set_id,
            rep_id=evidence.rep_id,
            rep_index=evidence.rep_index,
            external_load=evidence.external_load,
            start_index=start_index,
            end_index=end_index,
            start_time_s=start_time,
            end_time_s=end_time,
            boundary_parameters=boundary_parameters,
            processing_run_id=run.processing_run_id,
            provenance=provenance,
        )
    except (TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"phase processing provenance: {exc}",),
            (evidence.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


create_vbt_concentric_phase = qualify_vbt_concentric_phase


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTMetricResult:
    """One deterministic mean-concentric or sampled-peak velocity result."""

    observation: ScientificMeasurementObservation
    metric: VBTMetric
    evidence: VBTVelocitySeriesEvidence
    phase: VBTConcentricPhase

    def __post_init__(self) -> None:
        _validate_vbt_metric_result(self)

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def value_m_per_s(self) -> float:
        return self.value

    @property
    def method_identity_key(self) -> object:
        return _vbt_metric_method_key(self)


def _metric_spec(metric: VBTMetric) -> tuple[RegistryReference, RegistryReference, str]:
    if metric is VBTMetric.MEAN_CONCENTRIC_VELOCITY:
        return (
            VBT_MEAN_CONCENTRIC_VELOCITY_METRIC,
            VBT_MEAN_CONCENTRIC_VELOCITY_OPERATION,
            "integral(v dt) / exact concentric duration",
        )
    if metric is VBTMetric.PEAK_VELOCITY:
        return (
            VBT_PEAK_VELOCITY_METRIC,
            VBT_PEAK_VELOCITY_OPERATION,
            "sampled maximum(v) over exact concentric support",
        )
    raise ValueError("VBT metric is not registered for computation")


def _vbt_time_mean(evidence: VBTVelocitySeriesEvidence, phase: VBTConcentricPhase) -> float:
    values = evidence.series.samples[phase.start_index : phase.end_index + 1]
    area = math.fsum(
        0.5
        * (values[offset - 1] + values[offset])
        * (
            time_at(evidence.series.timebase, phase.start_index + offset)
            - time_at(evidence.series.timebase, phase.start_index + offset - 1)
        )
        for offset in range(1, len(values))
    )
    duration = phase.end_time_s - phase.start_time_s
    if duration <= 0:
        raise ValueError("VBT concentric phase duration must be positive")
    return area / duration


def _expected_vbt_metric_value(result: VBTMetricResult) -> float:
    return _calculate_vbt_value(result.evidence, result.phase, result.metric)


def _calculate_vbt_value(
    evidence: VBTVelocitySeriesEvidence,
    phase: VBTConcentricPhase,
    metric: VBTMetric,
) -> float:
    values = evidence.series.samples[phase.start_index : phase.end_index + 1]
    if metric is VBTMetric.MEAN_CONCENTRIC_VELOCITY:
        return _vbt_time_mean(evidence, phase)
    if metric is VBTMetric.PEAK_VELOCITY:
        return max(values)
    raise ValueError("mean propulsive velocity has no computational authority")


def _vbt_metric_method_key(result: VBTMetricResult) -> object:
    metric_reference, operation, equation = _metric_spec(result.metric)
    identity = result.evidence.identity
    return {
        "metric": metric_reference,
        "operation": operation,
        "equation": equation,
        "protocol": identity.semantic.protocol_identity,
        "acquisition": identity.acquisition,
        "source_processing_state": result.evidence.series.processing_state,
        "filtering": identity.processing.filtering,
        "filtering_status": identity.processing.filtering_status,
        "smoothing": identity.processing.smoothing,
        "resampling": identity.processing.resampling,
        "timebase": result.evidence.series.timebase,
        "phase_definition": result.phase.phase_definition,
        "phase_boundary_method": result.phase.boundary_method,
        "phase_boundary_convention": result.phase.boundary_convention,
        "phase_boundary_parameters": result.phase.boundary_parameters,
        "phase_support": (result.phase.start_index, result.phase.end_index),
        "load": result.evidence.external_load,
        "attachment": identity.acquisition.attachment_location,
        "sensor_modality": identity.acquisition.sensor_modality,
    }


def _require_vbt_output_lineage(
    observation: ScientificMeasurementObservation,
    *,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    source_entities: tuple[InstanceIdentifier, ...],
    expected_origins: tuple[ValueOrigin, ...] = (ValueOrigin.DYNAMISLM_DERIVED,),
) -> None:
    identity = observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("VBT output requires VBTMeasurementIdentity")
    if (
        identity.processing.registered_operation != operation
        or identity.version.processing_method != operation
        or identity.version.method_registry_version != STRENGTH_REGISTRY_VERSION
        or identity.version.software_version != RES66_SOFTWARE_VERSION
    ):
        raise ValueError("VBT output operation is not registered")
    if identity.processing.method_parameters != parameters:
        raise ValueError("VBT output parameters do not match its processing identity")
    runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(runs) != 1 or runs[0].method != operation or runs[0].parameters != parameters:
        raise ValueError("VBT output must preserve one matching processing run")
    if any(
        artifact_id
        not in tuple(artifact.artifact_id for artifact in observation.provenance.source_artifacts)
        for artifact_id in runs[0].source_artifact_ids
    ):
        raise ValueError("VBT output processing run names an absent source artifact")
    if observation.result.status is not ResultStatus.VALID:
        raise ValueError("VBT output must be valid")
    if observation.result.classification.value_origin not in expected_origins:
        raise ValueError("VBT output has an unregistered value origin")
    if observation.result.classification.scientific_roles:
        raise ValueError("VBT mechanical statistic must not infer a scientific role")
    run_id = runs[0].processing_run_id.qualified
    for source_entity in source_entities:
        if not any(
            edge.from_id == source_entity.qualified
            and edge.to_id == run_id
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in observation.provenance.lineage_edges
        ):
            raise ValueError("VBT output is missing exact source lineage")


def _validate_vbt_metric_result(result: VBTMetricResult) -> None:
    _validate_vbt_evidence(result.evidence)
    _validate_phase_for_evidence(result.evidence, result.phase)
    if result.evidence.phase != result.phase:
        raise ValueError("VBT result phase does not match the evidence phase")
    if result.metric not in {
        VBTMetric.MEAN_CONCENTRIC_VELOCITY,
        VBTMetric.PEAK_VELOCITY,
    }:
        raise ValueError("VBT metric result cannot represent MPV")
    metric_reference, operation, _ = _metric_spec(result.metric)
    identity = result.observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("VBT output requires VBTMeasurementIdentity")
    if (
        identity.semantic.construct != VBT_BAR_VELOCITY_CONSTRUCT
        or identity.semantic.metric_definition != metric_reference
        or identity.semantic.measurand != VBT_VELOCITY_MEASURAND
    ):
        raise ValueError("VBT output has the wrong construct, measurand, or metric")
    if identity.semantic.protocol_identity != result.evidence.identity.semantic.protocol_identity:
        raise ValueError("VBT output does not preserve protocol identity")
    if identity.acquisition != result.evidence.identity.acquisition:
        raise ValueError("VBT output does not preserve acquisition identity")
    source_processing = result.evidence.identity.processing
    if (
        identity.processing.phase_definitions != (VBT_CONCENTRIC_PHASE_DEFINITION,)
        or identity.processing.filtering != source_processing.filtering
        or identity.processing.filtering_status != source_processing.filtering_status
        or identity.processing.smoothing != source_processing.smoothing
        or identity.processing.resampling != source_processing.resampling
        or identity.processing.processing_state != StrengthProcessingState.DYNAMISLM_PROCESSED
    ):
        raise ValueError("VBT output does not preserve processing identity")
    if result.observation.context != result.evidence.observation.context:
        raise ValueError("VBT output context was rebound")
    if result.observation.result.unit != METER_PER_SECOND:
        raise ValueError("VBT output must use m/s")
    if _numeric_scalar(result.observation) != _expected_vbt_metric_value(result):
        raise ValueError("VBT output scalar does not reproduce from the source series")
    _require_vbt_output_lineage(
        result.observation,
        operation=operation,
        parameters=identity.processing.method_parameters,
        source_entities=(
            result.evidence.observation.observation_id,
            result.evidence.series.series_id,
            result.phase.phase_id,
            result.evidence.set_id,
            result.evidence.rep_id,
        ),
    )


def _vbt_metric_parameters(
    evidence: VBTVelocitySeriesEvidence,
    phase: VBTConcentricPhase,
    metric: VBTMetric,
    operation: RegistryReference,
    equation: str,
) -> tuple[MetadataEntry, ...]:
    metric_reference, _, _ = _metric_spec(metric)
    return (
        MetadataEntry("metric", metric.value),
        MetadataEntry("metric_definition", metric_reference.stable_id),
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("operation_version", operation.identifier.version),
        MetadataEntry("equation", equation),
        MetadataEntry("source_observation_id", evidence.observation.observation_id.qualified),
        MetadataEntry("source_series_id", evidence.series.series_id.qualified),
        MetadataEntry("source_artifact_id", evidence.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", evidence.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", evidence.identity.identity_id.stable_id),
        MetadataEntry("source_series_digest", evidence.source_series_digest),
        MetadataEntry("source_processing_state", evidence.series.processing_state.value),
        MetadataEntry("set_id", evidence.set_id.qualified),
        MetadataEntry("rep_id", evidence.rep_id.qualified),
        MetadataEntry("rep_index", evidence.rep_index),
        MetadataEntry("external_load", canonical_json(evidence.external_load)),
        MetadataEntry("phase_id", phase.phase_id.qualified),
        MetadataEntry("phase_definition", phase.phase_definition.stable_id),
        MetadataEntry("phase_boundary_method", phase.boundary_method.stable_id),
        MetadataEntry("phase_boundary_convention", phase.boundary_convention.stable_id),
        MetadataEntry("phase_boundary_parameters", canonical_json(phase.boundary_parameters)),
        MetadataEntry("phase_start_index", phase.start_index),
        MetadataEntry("phase_end_index", phase.end_index),
        MetadataEntry("phase_start_time_s", phase.start_time_s),
        MetadataEntry("phase_end_time_s", phase.end_time_s),
        MetadataEntry("timebase", canonical_json(evidence.series.timebase)),
        MetadataEntry("interpolation", "none"),
    )


def _build_vbt_metric_observation(
    *,
    evidence: VBTVelocitySeriesEvidence,
    phase: VBTConcentricPhase,
    metric: VBTMetric,
    operation: RegistryReference,
    equation: str,
    value: float,
    output_observation_id: InstanceIdentifier | None,
) -> ScientificMeasurementObservation:
    parameters = _vbt_metric_parameters(evidence, phase, metric, operation, equation)
    digest = canonical_hash(
        {"metric": metric, "operation": operation, "parameters": parameters, "value": value}
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"vbt-res66:{digest}"
    )
    if observation_id == evidence.observation.observation_id:
        raise ValueError("VBT derived observation must differ from source evidence")
    source_identity = evidence.identity
    processing = StrengthProcessingIdentity(
        phase_definitions=(VBT_CONCENTRIC_PHASE_DEFINITION,),
        registered_operation=operation,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=METER_PER_SECOND,
        sign_convention=source_identity.acquisition.sign_convention,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = VBTMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", f"vbt-res66-{digest}", STRENGTH_REGISTRY_VERSION
        ),
        semantic=replace(
            source_identity.semantic,
            construct=VBT_BAR_VELOCITY_CONSTRUCT,
            measurand=VBT_VELOCITY_MEASURAND,
            metric_definition=_metric_spec(metric)[0],
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"vbt-res66:{digest}"),
        content_digest=canonical_hash(
            {"value": value, "unit": METER_PER_SECOND, "parameters": parameters}
        ),
        media_type="application/vnd.dynamislm.vbt.scalar-metric",
        immutable=True,
    )
    base = _merge_provenance(
        evidence.observation.provenance, phase.provenance or evidence.observation.provenance
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"vbt-res66:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=operation,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=(evidence.observation.observation_id, phase.phase_id),
        source_acquisition_ids=tuple(item.acquisition_id for item in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    edges = list(provenance.lineage_edges)
    for entity_id in (evidence.series.series_id, evidence.set_id, evidence.rep_id):
        edge = LineageEdge(
            entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    provenance = replace(provenance, lineage_edges=tuple(edges))
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=evidence.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"vbt-res66:{digest}"),
            value=ScalarValue(value),
            unit=METER_PER_SECOND,
            classification=ScientificClassification(ValueOrigin.DYNAMISLM_DERIVED, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=(
                    "RES-66 deterministic VBT arithmetic; measurement uncertainty is not assessed."
                ),
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


def calculate_vbt_metric(
    evidence: VBTVelocitySeriesEvidence,
    metric: VBTMetric,
    *,
    phase: VBTConcentricPhase | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> VBTMetricResult | RefusalResult:
    """Calculate one registered bar-velocity statistic from exact phase data."""

    claim = "calculate registered VBT velocity metric"
    try:
        _validate_vbt_evidence(evidence)
        if not isinstance(metric, VBTMetric):
            raise ValueError("registered VBTMetric is required")
        if metric is VBTMetric.MEAN_PROPULSIVE_VELOCITY:
            return refuse_mean_propulsive_velocity(evidence)
        selected_phase = phase or evidence.phase
        if selected_phase is None:
            raise ValueError("qualified upstream concentric phase is required")
        _validate_phase_for_evidence(evidence, selected_phase)
        bound_evidence = (
            evidence if evidence.phase == selected_phase else evidence.with_phase(selected_phase)
        )
        metric_reference, operation, equation = _metric_spec(metric)
        del metric_reference
        value = _calculate_vbt_value(bound_evidence, selected_phase, metric)
    except (AttributeError, IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PHASE_SOURCE_MISMATCH,),
            (f"qualified VBT velocity source/phase: {exc}",),
            (evidence.observation.observation_id,)
            if isinstance(evidence, VBTVelocitySeriesEvidence)
            else (),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return _build_vbt_metric_result(
        bound_evidence, selected_phase, metric, operation, equation, output_observation_id, value
    )


def _build_vbt_metric_result(
    evidence: VBTVelocitySeriesEvidence,
    phase: VBTConcentricPhase,
    metric: VBTMetric,
    operation: RegistryReference,
    equation: str,
    output_observation_id: InstanceIdentifier | None,
    value: float,
) -> VBTMetricResult | RefusalResult:
    try:
        observation = _build_vbt_metric_observation(
            evidence=evidence,
            phase=phase,
            metric=metric,
            operation=operation,
            equation=equation,
            value=value,
            output_observation_id=output_observation_id,
        )
        return VBTMetricResult(observation, metric, evidence, phase)
    except (AttributeError, IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            "construct registered VBT velocity metric",
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"deterministic VBT result construction: {exc}",),
            (evidence.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def calculate_mean_concentric_velocity(
    evidence: VBTVelocitySeriesEvidence,
    *,
    phase: VBTConcentricPhase | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> VBTMetricResult | RefusalResult:
    return calculate_vbt_metric(
        evidence,
        VBTMetric.MEAN_CONCENTRIC_VELOCITY,
        phase=phase,
        output_observation_id=output_observation_id,
    )


def calculate_peak_velocity(
    evidence: VBTVelocitySeriesEvidence,
    *,
    phase: VBTConcentricPhase | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> VBTMetricResult | RefusalResult:
    return calculate_vbt_metric(
        evidence,
        VBTMetric.PEAK_VELOCITY,
        phase=phase,
        output_observation_id=output_observation_id,
    )


def refuse_mean_propulsive_velocity(
    evidence: VBTVelocitySeriesEvidence | None = None,
) -> RefusalResult:
    observation_ids = () if evidence is None else (evidence.observation.observation_id,)
    return _refusal(
        "calculate mean propulsive velocity",
        (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        (
            "registered propulsive acceleration criterion, gravity reference, differentiation, "
            "filtering, sampling, and phase-boundary semantics",
        ),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe_descriptions=(
            "mean concentric velocity and sampled peak velocity remain distinct "
            "describable metrics",
            "no mean concentric velocity is relabelled as mean propulsive velocity",
        ),
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTSuccessfulRepetition:
    """Explicit success criterion for a measured 1RM repetition."""

    evidence: VBTVelocitySeriesEvidence
    successful: bool
    success_criteria: RegistryReference = VBT_SUCCESSFUL_REPETITION_CRITERION

    def __post_init__(self) -> None:
        _validate_vbt_evidence(self.evidence)
        if not isinstance(self.successful, bool):
            raise ValueError("successful must be boolean")
        if self.success_criteria != VBT_SUCCESSFUL_REPETITION_CRITERION:
            raise ValueError("success criteria is not registered")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasuredOneRepMax:
    """Direct/source-reported strength result; never a model estimate."""

    observation: ScientificMeasurementObservation
    repetition: VBTSuccessfulRepetition
    selection_rule: RegistryReference = VBT_MEASURED_1RM_SELECTION_RULE

    def __post_init__(self) -> None:
        _validate_measured_1rm_result(self)

    @property
    def value_kg(self) -> float:
        return _numeric_scalar(self.observation)


def _load_value_kg(load: StrengthLoadIdentity) -> float:
    if load.unit != KILOGRAM:
        raise ValueError("strength load must use kg for this operation")
    if load.semantics not in {
        StrengthLoadSemantics.ADDED_EXTERNAL_LOAD,
        StrengthLoadSemantics.TOTAL_EXTERNAL_LOAD,
    }:
        raise ValueError("percentage or unresolved load is not a physical 1RM load")
    return load.value


def _load_definition_key(load: StrengthLoadIdentity) -> object:
    return {
        "unit": load.unit,
        "implement_type": load.implement_type,
        "semantics": load.semantics,
        "bar_mass_kg": load.bar_mass_kg,
        "source_reference": load.source_reference,
    }


def _build_measured_1rm_observation(
    repetition: VBTSuccessfulRepetition,
    *,
    output_observation_id: InstanceIdentifier | None,
) -> ScientificMeasurementObservation:
    evidence = repetition.evidence
    load_kg = _load_value_kg(evidence.external_load)
    parameters = (
        MetadataEntry("operation_id", VBT_MEASURED_1RM_OPERATION.stable_id),
        MetadataEntry("measurand", VBT_MEASURED_1RM_MEASURAND.stable_id),
        MetadataEntry("metric", VBT_MEASURED_1RM_METRIC.stable_id),
        MetadataEntry("source_observation_id", evidence.observation.observation_id.qualified),
        MetadataEntry("source_series_id", evidence.series.series_id.qualified),
        MetadataEntry("source_artifact_id", evidence.source_artifact.artifact_id.qualified),
        MetadataEntry("set_id", evidence.set_id.qualified),
        MetadataEntry("rep_id", evidence.rep_id.qualified),
        MetadataEntry("rep_index", evidence.rep_index),
        MetadataEntry("external_load", canonical_json(evidence.external_load)),
        MetadataEntry("successful", repetition.successful),
        MetadataEntry("success_criteria", repetition.success_criteria.stable_id),
        MetadataEntry("selection_rule", VBT_MEASURED_1RM_SELECTION_RULE.stable_id),
    )
    digest = canonical_hash(
        {"operation": VBT_MEASURED_1RM_OPERATION, "parameters": parameters}
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"vbt-measured-1rm:{digest}"
    )
    source_identity = evidence.identity
    processing = StrengthProcessingIdentity(
        registered_operation=VBT_MEASURED_1RM_OPERATION,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=KILOGRAM,
        sign_convention=source_identity.acquisition.sign_convention,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = VBTMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"vbt-measured-1rm-{digest}",
            STRENGTH_REGISTRY_VERSION,
        ),
        semantic=replace(
            source_identity.semantic,
            construct=STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT,
            measurand=VBT_MEASURED_1RM_MEASURAND,
            metric_definition=VBT_MEASURED_1RM_METRIC,
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=VBT_MEASURED_1RM_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"vbt-measured-1rm:{digest}"),
        content_digest=canonical_hash(
            {"value": load_kg, "unit": KILOGRAM, "parameters": parameters}
        ),
        media_type="application/vnd.dynamislm.vbt.measured-1rm",
        immutable=True,
    )
    base = evidence.observation.provenance
    if evidence.phase is not None and evidence.phase.provenance is not None:
        base = _merge_provenance(base, evidence.phase.provenance)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"vbt-measured-1rm:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=VBT_MEASURED_1RM_OPERATION,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=(evidence.observation.observation_id,),
        source_acquisition_ids=(evidence.acquisition.acquisition_id,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        output_artifacts=(output_artifact,),
    )
    edges = list(provenance.lineage_edges)
    for entity_id in (evidence.series.series_id, evidence.set_id, evidence.rep_id):
        edge = LineageEdge(
            entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    if evidence.phase is not None:
        edge = LineageEdge(
            evidence.phase.phase_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=evidence.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"vbt-measured-1rm:{digest}"),
            value=ScalarValue(load_kg),
            unit=KILOGRAM,
            classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=replace(provenance, lineage_edges=tuple(edges)),
    )


def _validate_measured_1rm_result(result: MeasuredOneRepMax) -> None:
    repetition = result.repetition
    if not repetition.successful:
        raise ValueError("measured 1RM requires an explicitly successful repetition")
    if result.selection_rule != VBT_MEASURED_1RM_SELECTION_RULE:
        raise ValueError("measured 1RM selection rule is not registered")
    evidence = repetition.evidence
    _validate_vbt_evidence(evidence)
    identity = result.observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("measured 1RM requires VBT identity")
    if (
        identity.semantic.construct != STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT
        or identity.semantic.measurand != VBT_MEASURED_1RM_MEASURAND
        or identity.semantic.metric_definition != VBT_MEASURED_1RM_METRIC
    ):
        raise ValueError("measured 1RM has the wrong scientific identity")
    if identity.processing.registered_operation != VBT_MEASURED_1RM_OPERATION:
        raise ValueError("measured 1RM has the wrong operation")
    if (
        identity.semantic.protocol_identity != evidence.identity.semantic.protocol_identity
        or identity.acquisition != evidence.identity.acquisition
    ):
        raise ValueError("measured 1RM does not preserve protocol/acquisition identity")
    source_processing = evidence.identity.processing
    if (
        identity.processing.filtering != source_processing.filtering
        or identity.processing.filtering_status != source_processing.filtering_status
        or identity.processing.smoothing != source_processing.smoothing
        or identity.processing.resampling != source_processing.resampling
        or identity.processing.processing_state != StrengthProcessingState.DYNAMISLM_PROCESSED
    ):
        raise ValueError("measured 1RM does not preserve processing identity")
    if result.observation.context != evidence.observation.context:
        raise ValueError("measured 1RM output context was rebound")
    if result.observation.result.unit != KILOGRAM:
        raise ValueError("measured 1RM must use kg")
    if result.observation.result.classification.value_origin not in {
        ValueOrigin.DIRECT_MEASUREMENT,
        ValueOrigin.SOURCE_REPORTED,
    }:
        raise ValueError("measured 1RM cannot carry a model-estimate origin")
    if result.value_kg != _load_value_kg(evidence.external_load):
        raise ValueError("measured 1RM scalar does not equal the successful physical load")
    parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
    if (
        parameters.get("success_criteria") != VBT_SUCCESSFUL_REPETITION_CRITERION.stable_id
        or parameters.get("selection_rule") != VBT_MEASURED_1RM_SELECTION_RULE.stable_id
        or parameters.get("rep_id") != evidence.rep_id.qualified
    ):
        raise ValueError("measured 1RM does not preserve success/rep identity")
    _require_vbt_output_lineage(
        result.observation,
        operation=VBT_MEASURED_1RM_OPERATION,
        parameters=identity.processing.method_parameters,
        source_entities=(
            evidence.observation.observation_id,
            evidence.series.series_id,
            evidence.set_id,
            evidence.rep_id,
            *((evidence.phase.phase_id,) if evidence.phase is not None else ()),
        ),
        expected_origins=(ValueOrigin.DIRECT_MEASUREMENT, ValueOrigin.SOURCE_REPORTED),
    )


def build_measured_1rm(
    repetition: VBTSuccessfulRepetition,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> MeasuredOneRepMax | RefusalResult:
    """Create a direct measured 1RM from a successful typed repetition."""

    claim = "build measured 1RM from a successful repetition"
    try:
        if not isinstance(repetition, VBTSuccessfulRepetition):
            raise ValueError("VBTSuccessfulRepetition is required")
        if not repetition.successful:
            raise ValueError("repetition is not successful")
        _load_value_kg(repetition.evidence.external_load)
        observation = _build_measured_1rm_observation(
            repetition, output_observation_id=output_observation_id
        )
        return MeasuredOneRepMax(observation, repetition)
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.MEASURAND_MISMATCH,),
            (f"successful physical load and direct repetition identity: {exc}",),
            (repetition.evidence.observation.observation_id,)
            if isinstance(repetition, VBTSuccessfulRepetition)
            else (),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TerminalVelocityAssumption:
    """Registered terminal velocity assumption for one model application."""

    reference: RegistryReference
    value_m_per_s: float
    description: str

    def __post_init__(self) -> None:
        if self.reference != VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY:
            raise ValueError("terminal velocity assumption is not registered")
        if _finite(self.value_m_per_s, "terminal velocity") != 0.17:
            raise ValueError("the registered Smith-machine bench terminal velocity is 0.17 m/s")
        if not self.description.strip():
            raise ValueError("terminal velocity description must not be empty")


SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017 = TerminalVelocityAssumption(
    reference=VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY,
    value_m_per_s=0.17,
    description=(
        "General 1RM velocity reported for the paused and touch-and-go Smith-machine bench press."
    ),
)
VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017 = SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LoadVelocityModel:
    """Individual linear load-velocity fit with all calibration inputs retained."""

    model_id: InstanceIdentifier
    model_reference: RegistryReference
    regression_method: RegistryReference
    athlete_id: InstanceIdentifier
    session_id: InstanceIdentifier
    test_instance_id: InstanceIdentifier
    population_context: str
    protocol_identity: StrengthProtocolIdentity
    device_identity: StrengthAcquisitionIdentity
    velocity_metric: VBTMetric
    calibration_results: tuple[VBTMetricResult, ...]
    calibration_loads: tuple[StrengthLoadIdentity, ...]
    calibration_velocities_m_per_s: tuple[float, ...]
    slope_m_per_s_per_kg: float
    intercept_m_per_s: float
    r_squared: float
    root_mean_squared_error_m_per_s: float
    equation: str
    software_version: str
    terminal_velocity_assumption: TerminalVelocityAssumption | None = None
    source_provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        _validate_load_velocity_model(self)

    @property
    def coefficients(self) -> tuple[float, float]:
        return self.intercept_m_per_s, self.slope_m_per_s_per_kg

    @property
    def model_estimate_value_origin(self) -> ValueOrigin:
        return ValueOrigin.MODEL_ESTIMATE

    @property
    def fit_method(self) -> RegistryReference:
        return self.regression_method

    @property
    def calibration_point_count(self) -> int:
        return len(self.calibration_results)

    @property
    def terminal_velocity_m_per_s(self) -> float | None:
        return (
            None
            if self.terminal_velocity_assumption is None
            else self.terminal_velocity_assumption.value_m_per_s
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EstimatedOneRepMax:
    """Model-estimated 1RM; constructor-level origin is never measured."""

    observation: ScientificMeasurementObservation
    model: LoadVelocityModel
    terminal_velocity_assumption: TerminalVelocityAssumption

    def __post_init__(self) -> None:
        _validate_estimated_1rm_result(self)

    @property
    def value_kg(self) -> float:
        return _numeric_scalar(self.observation)


def _ols_fit(xs: tuple[float, ...], ys: tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("linear load-velocity fit requires at least two paired points")
    mean_x = math.fsum(xs) / len(xs)
    mean_y = math.fsum(ys) / len(ys)
    ss_xx = math.fsum((value - mean_x) ** 2 for value in xs)
    if ss_xx <= 0:
        raise ValueError("calibration loads must contain at least two distinct values")
    covariance = math.fsum(
        (x_value - mean_x) * (y_value - mean_y) for x_value, y_value in zip(xs, ys, strict=True)
    )
    slope = covariance / ss_xx
    intercept = mean_y - slope * mean_x
    residuals = tuple(
        y_value - (intercept + slope * x_value) for x_value, y_value in zip(xs, ys, strict=True)
    )
    residual_sum_squares = math.fsum(value * value for value in residuals)
    total_sum_squares = math.fsum((value - mean_y) ** 2 for value in ys)
    if total_sum_squares <= 0:
        raise ValueError("calibration velocities must vary")
    r_squared = 1.0 - residual_sum_squares / total_sum_squares
    rmse = math.sqrt(residual_sum_squares / len(xs))
    return intercept, slope, r_squared, rmse


def _acquisition_method_key(acquisition: StrengthAcquisitionIdentity) -> object:
    return {
        "device": acquisition.device,
        "provider": acquisition.provider,
        "sensor_modality": acquisition.sensor_modality,
        "attachment_location": acquisition.attachment_location,
        "sampling": acquisition.sampling,
        "unit": acquisition.unit,
        "physical_axis": acquisition.physical_axis,
        "reference_frame": acquisition.reference_frame,
        "sign_convention": acquisition.sign_convention,
        "timebase": (
            _comparison_timebase_key(acquisition.timebase)
            if acquisition.timebase is not None
            else None
        ),
    }


def _protocol_model_key(protocol: StrengthProtocolIdentity) -> object:
    """Protocol identity for a variable-load calibration, excluding load value."""

    return replace(
        protocol, external_load_status=StrengthExternalLoadStatus.UNKNOWN, external_load=None
    )


def _validate_load_velocity_model(model: LoadVelocityModel) -> None:
    if model.model_id.instance_type != "load-velocity-model":
        raise ValueError("model_id must identify a load-velocity-model")
    if (
        model.model_reference != VBT_LOAD_VELOCITY_MODEL
        or model.regression_method != VBT_LINEAR_REGRESSION_METHOD
    ):
        raise ValueError("load-velocity model or regression method is not registered")
    if (
        model.athlete_id.instance_type != "athlete"
        or model.session_id.instance_type != "session"
        or model.test_instance_id.instance_type != "test-instance"
    ):
        raise ValueError("load-velocity model context identifiers are invalid")
    if not model.population_context.strip():
        raise ValueError("model population_context must not be empty")
    if model.equation != "velocity_m_per_s = intercept_m_per_s + slope_m_per_s_per_kg * load_kg":
        raise ValueError("load-velocity model equation is not registered")
    if model.software_version != RES66_SOFTWARE_VERSION:
        raise ValueError("load-velocity model software version is not registered")
    if model.velocity_metric not in {VBTMetric.MEAN_CONCENTRIC_VELOCITY, VBTMetric.PEAK_VELOCITY}:
        raise ValueError("load-velocity model metric is not registered")
    require_tuple(model.calibration_results, "calibration_results")
    require_tuple(model.calibration_loads, "calibration_loads")
    require_tuple(model.calibration_velocities_m_per_s, "calibration_velocities_m_per_s")
    if (
        len(model.calibration_results) < 2
        or len(model.calibration_results) != len(model.calibration_loads)
        or len(model.calibration_results) != len(model.calibration_velocities_m_per_s)
    ):
        raise ValueError("load-velocity model calibration arrays must have equal length >= 2")
    first = model.calibration_results[0]
    if (
        first.observation.context.athlete_id != model.athlete_id
        or first.observation.context.session_id != model.session_id
        or first.observation.context.test_instance_id != model.test_instance_id
    ):
        raise ValueError("model context does not match calibration context")
    if first.observation.context.population_context != model.population_context:
        raise ValueError("model population applicability does not match calibration")
    if first.evidence.identity.semantic.protocol_identity is None or _protocol_model_key(
        first.evidence.identity.semantic.protocol_identity
    ) != _protocol_model_key(model.protocol_identity):
        raise ValueError("model protocol identity does not match calibration")
    if _acquisition_method_key(first.evidence.identity.acquisition) != _acquisition_method_key(
        model.device_identity
    ):
        raise ValueError("model device/acquisition identity does not match calibration")
    load_definition = _load_definition_key(model.calibration_loads[0])
    for index, result in enumerate(model.calibration_results):
        if not isinstance(result, VBTMetricResult) or result.metric is not model.velocity_metric:
            raise ValueError("model calibration metric mismatch")
        if (
            result.observation.context.athlete_id != model.athlete_id
            or result.observation.context.session_id != model.session_id
            or result.observation.context.test_instance_id != model.test_instance_id
        ):
            raise ValueError("model calibration context mismatch")
        if result.evidence.identity.semantic.protocol_identity is None or _protocol_model_key(
            result.evidence.identity.semantic.protocol_identity
        ) != _protocol_model_key(model.protocol_identity):
            raise ValueError("model calibration protocol mismatch")
        if _acquisition_method_key(result.evidence.identity.acquisition) != _acquisition_method_key(
            model.device_identity
        ):
            raise ValueError("model calibration device mismatch")
        if _load_definition_key(model.calibration_loads[index]) != load_definition:
            raise ValueError("model calibration load definition mismatch")
        if result.evidence.external_load != model.calibration_loads[index]:
            raise ValueError("model calibration load is not copied from its source result")
        if model.calibration_velocities_m_per_s[index] != result.value:
            raise ValueError("model calibration velocity is not copied from its source result")
        _finite(model.calibration_velocities_m_per_s[index], "calibration velocity")
    xs = tuple(_load_value_kg(load) for load in model.calibration_loads)
    ys = tuple(model.calibration_velocities_m_per_s)
    intercept, slope, r_squared, rmse = _ols_fit(xs, ys)
    if slope >= 0:
        raise ValueError("individual load-velocity model requires a negative slope")
    if (
        model.intercept_m_per_s != intercept
        or model.slope_m_per_s_per_kg != slope
        or model.r_squared != r_squared
        or model.root_mean_squared_error_m_per_s != rmse
    ):
        raise ValueError("load-velocity coefficients or diagnostics do not reproduce")
    for name in (
        "slope_m_per_s_per_kg",
        "intercept_m_per_s",
        "r_squared",
        "root_mean_squared_error_m_per_s",
    ):
        _finite(getattr(model, name), name)
    if not 0 <= model.r_squared <= 1:
        raise ValueError("r_squared must be between zero and one")
    if model.terminal_velocity_assumption is not None and not isinstance(
        model.terminal_velocity_assumption, TerminalVelocityAssumption
    ):
        raise ValueError("terminal velocity assumption is not typed")
    expected_provenance = tuple(
        result.observation.provenance for result in model.calibration_results
    )
    if model.source_provenance and model.source_provenance != expected_provenance:
        raise ValueError("model source provenance does not preserve calibration provenance")


def fit_load_velocity_model(
    calibration_results: tuple[VBTMetricResult, ...],
    *,
    terminal_velocity_assumption: TerminalVelocityAssumption | None = None,
    output_model_id: InstanceIdentifier | None = None,
) -> LoadVelocityModel | RefusalResult:
    """Fit one individual linear load-velocity relationship from typed points."""

    claim = "fit registered individual linear load-velocity model"
    try:
        require_tuple(calibration_results, "calibration_results")
        if len(calibration_results) < 2 or any(
            not isinstance(item, VBTMetricResult) for item in calibration_results
        ):
            raise ValueError("at least two typed VBT metric results are required")
        first = calibration_results[0]
        if first.metric not in {VBTMetric.MEAN_CONCENTRIC_VELOCITY, VBTMetric.PEAK_VELOCITY}:
            raise ValueError("load-velocity model requires a registered velocity metric")
        load_definition = _load_definition_key(first.evidence.external_load)
        if _load_value_kg(first.evidence.external_load) < 0:
            raise ValueError("load must be non-negative")
        for result in calibration_results[1:]:
            if result.metric is not first.metric:
                raise ValueError("calibration points must use one velocity metric")
            if (
                result.observation.context.athlete_id != first.observation.context.athlete_id
                or result.observation.context.session_id != first.observation.context.session_id
                or result.observation.context.test_instance_id
                != first.observation.context.test_instance_id
            ):
                raise ValueError("calibration points must share athlete/session/test context")
            if (
                result.evidence.identity.semantic.protocol_identity is None
                or first.evidence.identity.semantic.protocol_identity is None
                or _protocol_model_key(result.evidence.identity.semantic.protocol_identity)
                != _protocol_model_key(first.evidence.identity.semantic.protocol_identity)
            ):
                raise ValueError("calibration points must share exact protocol identity")
            if _acquisition_method_key(
                result.evidence.identity.acquisition
            ) != _acquisition_method_key(first.evidence.identity.acquisition):
                raise ValueError("calibration points must share device/acquisition identity")
            if _load_definition_key(result.evidence.external_load) != load_definition:
                raise ValueError("calibration points must share physical load definition")
        loads = tuple(item.evidence.external_load for item in calibration_results)
        xs = tuple(_load_value_kg(load) for load in loads)
        if len(set(xs)) != len(xs):
            raise ValueError("calibration loads must be distinct")
        ys = tuple(item.value for item in calibration_results)
        intercept, slope, r_squared, rmse = _ols_fit(xs, ys)
        if slope >= 0:
            raise ValueError("load-velocity relationship must have a negative slope")
        source_protocol = first.evidence.identity.semantic.protocol_identity
        if source_protocol is None:
            raise ValueError("complete protocol identity is required for a load-velocity model")
        protocol = replace(
            source_protocol,
            external_load_status=StrengthExternalLoadStatus.UNKNOWN,
            external_load=None,
        )
        device_identity = replace(
            first.evidence.identity.acquisition,
            raw_artifact=None,
            acquisition_instance_id=None,
        )
        digest = canonical_hash(
            {
                "model": VBT_LOAD_VELOCITY_MODEL,
                "source_observation_ids": tuple(
                    item.observation.observation_id for item in calibration_results
                ),
                "loads": loads,
                "velocities": ys,
                "terminal_velocity_assumption": terminal_velocity_assumption,
            }
        ).removeprefix("sha256:")[:24]
        model_id = output_model_id or InstanceIdentifier("load-velocity-model", f"vbt:{digest}")
        model = LoadVelocityModel(
            model_id=model_id,
            model_reference=VBT_LOAD_VELOCITY_MODEL,
            regression_method=VBT_LINEAR_REGRESSION_METHOD,
            athlete_id=first.observation.context.athlete_id,
            session_id=first.observation.context.session_id,
            test_instance_id=first.observation.context.test_instance_id,
            population_context=first.observation.context.population_context,
            protocol_identity=protocol,
            device_identity=device_identity,
            velocity_metric=first.metric,
            calibration_results=calibration_results,
            calibration_loads=loads,
            calibration_velocities_m_per_s=ys,
            slope_m_per_s_per_kg=slope,
            intercept_m_per_s=intercept,
            r_squared=r_squared,
            root_mean_squared_error_m_per_s=rmse,
            equation=("velocity_m_per_s = intercept_m_per_s + slope_m_per_s_per_kg * load_kg"),
            software_version=RES66_SOFTWARE_VERSION,
            terminal_velocity_assumption=terminal_velocity_assumption,
            source_provenance=tuple(item.observation.provenance for item in calibration_results),
        )
        return model
    except (AttributeError, IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (
                "same protocol/device/metric physical calibration points and negative OLS "
                f"slope: {exc}",
            ),
            tuple(
                item.observation.observation_id
                for item in calibration_results
                if isinstance(item, VBTMetricResult)
            ),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def _estimated_1rm_value(
    model: LoadVelocityModel,
    terminal_velocity_assumption: TerminalVelocityAssumption,
) -> float:
    if model.velocity_metric is not VBTMetric.MEAN_CONCENTRIC_VELOCITY:
        raise ValueError("V1 estimated 1RM requires mean concentric velocity")
    value = (
        terminal_velocity_assumption.value_m_per_s - model.intercept_m_per_s
    ) / model.slope_m_per_s_per_kg
    if not math.isfinite(value) or value <= 0:
        raise ValueError("estimated 1RM is not a finite positive physical load")
    maximum_calibration_load = max(_load_value_kg(load) for load in model.calibration_loads)
    minimum_calibration_velocity = min(model.calibration_velocities_m_per_s)
    if (
        terminal_velocity_assumption.value_m_per_s >= minimum_calibration_velocity
        or value <= maximum_calibration_load
    ):
        raise ValueError("terminal velocity requires unsupported non-extrapolating 1RM application")
    return value


def _model_output_lineage(
    observation: ScientificMeasurementObservation,
    *,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    source_entities: tuple[InstanceIdentifier, ...],
) -> None:
    identity = observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("model output requires VBT measurement identity")
    if (
        identity.processing.registered_operation != operation
        or identity.version.processing_method != operation
        or identity.version.method_registry_version != STRENGTH_REGISTRY_VERSION
        or identity.version.software_version != RES66_SOFTWARE_VERSION
        or identity.processing.method_parameters != parameters
    ):
        raise ValueError("model output processing identity is not preserved")
    runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(runs) != 1 or runs[0].method != operation or runs[0].parameters != parameters:
        raise ValueError("model output must preserve one producing processing run")
    if any(
        artifact_id
        not in tuple(artifact.artifact_id for artifact in observation.provenance.source_artifacts)
        for artifact_id in runs[0].source_artifact_ids
    ):
        raise ValueError("model output processing run names an absent source artifact")
    if observation.result.classification.value_origin is not ValueOrigin.MODEL_ESTIMATE:
        raise ValueError("model output must be classified MODEL_ESTIMATE")
    if observation.result.status is not ResultStatus.VALID:
        raise ValueError("model output must be valid")
    if observation.result.classification.scientific_roles:
        raise ValueError("model output must not infer a scientific role")
    run_id = runs[0].processing_run_id.qualified
    for source_entity in source_entities:
        if not any(
            edge.from_id == source_entity.qualified
            and edge.to_id == run_id
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in observation.provenance.lineage_edges
        ):
            raise ValueError("model output is missing calibration lineage")


def _build_estimated_1rm_observation(
    model: LoadVelocityModel,
    terminal_velocity_assumption: TerminalVelocityAssumption,
    value: float,
    output_observation_id: InstanceIdentifier | None,
) -> ScientificMeasurementObservation:
    first = model.calibration_results[0]
    source_identity = first.evidence.identity
    parameters = (
        MetadataEntry("operation_id", VBT_ESTIMATED_1RM_OPERATION.stable_id),
        MetadataEntry("model_id", model.model_id.qualified),
        MetadataEntry("model_reference", model.model_reference.stable_id),
        MetadataEntry("regression_method", model.regression_method.stable_id),
        MetadataEntry("velocity_metric", model.velocity_metric.value),
        MetadataEntry(
            "load_definition", canonical_json(_load_definition_key(model.calibration_loads[0]))
        ),
        MetadataEntry("calibration_loads", canonical_json(model.calibration_loads)),
        MetadataEntry(
            "calibration_velocities_m_per_s", canonical_json(model.calibration_velocities_m_per_s)
        ),
        MetadataEntry("intercept_m_per_s", model.intercept_m_per_s),
        MetadataEntry("slope_m_per_s_per_kg", model.slope_m_per_s_per_kg),
        MetadataEntry("terminal_velocity_assumption", canonical_json(terminal_velocity_assumption)),
        MetadataEntry(
            "equation", "(terminal_velocity_m_per_s - intercept_m_per_s) / slope_m_per_s_per_kg"
        ),
        MetadataEntry(
            "calibration_observation_ids",
            canonical_json(
                tuple(item.observation.observation_id for item in model.calibration_results)
            ),
        ),
    )
    digest = canonical_hash(
        {"operation": VBT_ESTIMATED_1RM_OPERATION, "parameters": parameters, "value": value}
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"vbt-estimated-1rm:{digest}"
    )
    processing = StrengthProcessingIdentity(
        registered_operation=VBT_ESTIMATED_1RM_OPERATION,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=KILOGRAM,
        sign_convention=source_identity.acquisition.sign_convention,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = VBTMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"vbt-estimated-1rm-{digest}",
            STRENGTH_REGISTRY_VERSION,
        ),
        semantic=replace(
            source_identity.semantic,
            construct=STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT,
            measurand=VBT_ESTIMATED_1RM_MEASURAND,
            metric_definition=VBT_ESTIMATED_1RM_METRIC,
            protocol=source_identity.semantic.protocol,
            protocol_identity=model.protocol_identity,
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=VBT_ESTIMATED_1RM_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"vbt-estimated-1rm:{digest}"),
        content_digest=canonical_hash({"value": value, "unit": KILOGRAM, "parameters": parameters}),
        media_type="application/vnd.dynamislm.vbt.estimated-1rm",
        immutable=True,
    )
    base = model.calibration_results[0].observation.provenance
    for result in model.calibration_results[1:]:
        base = _merge_provenance(base, result.observation.provenance)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"vbt-estimated-1rm:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=VBT_ESTIMATED_1RM_OPERATION,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=tuple(
            result.observation.observation_id for result in model.calibration_results
        ),
        source_acquisition_ids=tuple(item.acquisition_id for item in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    edges = list(provenance.lineage_edges)
    for result in model.calibration_results:
        for entity_id in (
            result.evidence.series.series_id,
            result.evidence.set_id,
            result.evidence.rep_id,
        ):
            edge = LineageEdge(
                entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
            )
            if edge not in edges:
                edges.append(edge)
        edge = LineageEdge(
            model.model_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=first.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"vbt-estimated-1rm:{digest}"),
            value=ScalarValue(value),
            unit=KILOGRAM,
            classification=ScientificClassification(ValueOrigin.MODEL_ESTIMATE, ()),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.LIMITED,
                description="Load-velocity model error is not propagated by RES-66.",
            ),
            status=ResultStatus.VALID,
        ),
        provenance=replace(provenance, lineage_edges=tuple(edges)),
    )


def _validate_estimated_1rm_result(result: EstimatedOneRepMax) -> None:
    model = result.model
    _validate_load_velocity_model(model)
    expected = _estimated_1rm_value(model, result.terminal_velocity_assumption)
    identity = result.observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("estimated 1RM requires VBT identity")
    if (
        identity.semantic.construct != STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT
        or identity.semantic.measurand != VBT_ESTIMATED_1RM_MEASURAND
        or identity.semantic.metric_definition != VBT_ESTIMATED_1RM_METRIC
    ):
        raise ValueError("estimated 1RM has the wrong identity")
    if identity.processing.registered_operation != VBT_ESTIMATED_1RM_OPERATION:
        raise ValueError("estimated 1RM has the wrong operation")
    source_identity = model.calibration_results[0].evidence.identity
    if identity.semantic.protocol_identity is None:
        raise ValueError("estimated 1RM protocol identity is unresolved")
    if _protocol_model_key(identity.semantic.protocol_identity) != _protocol_model_key(
        model.protocol_identity
    ):
        raise ValueError("estimated 1RM does not preserve model protocol identity")
    if identity.acquisition != source_identity.acquisition:
        raise ValueError("estimated 1RM does not preserve calibration acquisition identity")
    if (
        identity.processing.filtering != source_identity.processing.filtering
        or identity.processing.filtering_status != source_identity.processing.filtering_status
        or identity.processing.smoothing != source_identity.processing.smoothing
        or identity.processing.resampling != source_identity.processing.resampling
        or identity.processing.processing_state != StrengthProcessingState.DYNAMISLM_PROCESSED
    ):
        raise ValueError("estimated 1RM does not preserve processing identity")
    if result.observation.context != model.calibration_results[0].observation.context:
        raise ValueError("estimated 1RM output context was rebound")
    if (
        result.observation.result.unit != KILOGRAM
        or result.observation.result.classification.value_origin is not ValueOrigin.MODEL_ESTIMATE
    ):
        raise ValueError("estimated 1RM is not a model estimate in kilograms")
    if _numeric_scalar(result.observation) != expected:
        raise ValueError("estimated 1RM scalar does not reproduce from model coefficients")
    parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
    if parameters.get("model_id") != model.model_id.qualified or parameters.get(
        "terminal_velocity_assumption"
    ) != canonical_json(result.terminal_velocity_assumption):
        raise ValueError("estimated 1RM does not preserve model/terminal assumption")
    _model_output_lineage(
        result.observation,
        operation=VBT_ESTIMATED_1RM_OPERATION,
        parameters=identity.processing.method_parameters,
        source_entities=tuple(
            result_.observation.observation_id for result_ in model.calibration_results
        ),
    )


def estimate_1rm_from_load_velocity_model(
    model: LoadVelocityModel,
    terminal_velocity_assumption: TerminalVelocityAssumption | None = None,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> EstimatedOneRepMax | RefusalResult:
    """Estimate 1RM only under the registered Smith-machine bench assumption."""

    claim = "estimate 1RM from registered individual load-velocity model"
    try:
        _validate_load_velocity_model(model)
        assumption = terminal_velocity_assumption or model.terminal_velocity_assumption
        if assumption is None:
            raise ValueError("explicit registered terminal velocity assumption is required")
        if not isinstance(assumption, TerminalVelocityAssumption):
            raise ValueError("terminal velocity assumption must be typed")
        if model.protocol_identity.test_family is not StrengthTestFamily.BENCH_PRESS_VBT:
            raise ValueError("RES-66 V1 terminal velocity is not registered for squat VBT")
        if model.protocol_identity.equipment_mode is not StrengthEquipmentMode.SMITH_MACHINE:
            raise ValueError(
                "RES-66 V1 terminal velocity is registered only for Smith-machine bench press"
            )
        value = _estimated_1rm_value(model, assumption)
        observation = _build_estimated_1rm_observation(
            model, assumption, value, output_observation_id
        )
        return EstimatedOneRepMax(observation, model, assumption)
    except (AttributeError, IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.UNKNOWN_THRESHOLD,),
            (f"registered protocol-specific terminal velocity and model: {exc}",),
            tuple(item.observation.observation_id for item in model.calibration_results)
            if isinstance(model, LoadVelocityModel)
            else (),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )


def refuse_estimated_1rm_as_measured(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "relabel estimated 1RM as measured strength",
        (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
        ("MODEL_ESTIMATE and DIRECT_MEASUREMENT are independent value-origin categories",),
        observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        safe_descriptions=(
            "the model estimate remains describable as an estimated 1RM",
            "no measured 1RM is created without a successful direct repetition",
        ),
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VBTVelocityLossResult:
    """Mechanical within-set velocity loss with an explicit reference rule."""

    observation: ScientificMeasurementObservation
    current: VBTMetricResult
    repetitions: tuple[VBTMetricResult, ...]
    reference_rule: VBTVelocityLossReference
    reference_repetition: VBTMetricResult

    def __post_init__(self) -> None:
        _validate_velocity_loss_result(self)

    @property
    def value_percent(self) -> float:
        return _numeric_scalar(self.observation)


def _velocity_loss_reference_reference(rule: VBTVelocityLossReference) -> RegistryReference:
    return {
        VBTVelocityLossReference.FIRST_REPETITION: VBT_FIRST_REPETITION_REFERENCE,
        VBTVelocityLossReference.FASTEST_REPETITION: VBT_FASTEST_REPETITION_REFERENCE,
        VBTVelocityLossReference.BEST_PREVIOUS_REPETITION: VBT_BEST_PREVIOUS_REPETITION_REFERENCE,
    }[rule]


def _within_set_method_key(result: VBTMetricResult) -> object:
    identity = result.evidence.identity
    return {
        "metric": result.metric,
        "protocol": identity.semantic.protocol_identity,
        "acquisition_method": _acquisition_method_key(identity.acquisition),
        "filtering": identity.processing.filtering,
        "filtering_status": identity.processing.filtering_status,
        "smoothing": identity.processing.smoothing,
        "resampling": identity.processing.resampling,
        "phase_definition": result.phase.phase_definition,
        "phase_boundary_method": result.phase.boundary_method,
        "phase_boundary_convention": result.phase.boundary_convention,
        "phase_boundary_parameters": result.phase.boundary_parameters,
    }


def _validate_same_set_repetitions(
    repetitions: tuple[VBTMetricResult, ...],
) -> None:
    if not repetitions:
        raise ValueError("at least one VBT repetition is required")
    first = repetitions[0]
    for result in repetitions:
        _validate_vbt_metric_result(result)
        if result.evidence.set_id != first.evidence.set_id:
            raise ValueError("velocity-loss repetitions must belong to one set")
        if (
            result.evidence.observation.context.athlete_id
            != first.evidence.observation.context.athlete_id
            or result.evidence.observation.context.session_id
            != first.evidence.observation.context.session_id
            or result.evidence.observation.context.test_instance_id
            != first.evidence.observation.context.test_instance_id
        ):
            raise ValueError("velocity-loss repetitions must share athlete/session/test context")
        if result.evidence.external_load != first.evidence.external_load:
            raise ValueError("velocity-loss repetitions must preserve exact load identity")
        if _within_set_method_key(result) != _within_set_method_key(first):
            raise ValueError("velocity-loss repetitions must preserve metric/phase/device identity")
    if len({result.evidence.rep_id for result in repetitions}) != len(repetitions):
        raise ValueError("velocity-loss repetitions must have distinct rep identities")


def _select_velocity_loss_reference(
    repetitions: tuple[VBTMetricResult, ...],
    current: VBTMetricResult,
    rule: VBTVelocityLossReference,
) -> VBTMetricResult:
    if rule is VBTVelocityLossReference.FIRST_REPETITION:
        return min(repetitions, key=lambda item: item.evidence.rep_index)
    if rule is VBTVelocityLossReference.FASTEST_REPETITION:
        return max(repetitions, key=lambda item: (item.value, -item.evidence.rep_index))
    previous = tuple(
        result for result in repetitions if result.evidence.rep_index < current.evidence.rep_index
    )
    if not previous:
        raise ValueError("best-previous-repetition reference requires a previous repetition")
    return max(previous, key=lambda item: (item.value, -item.evidence.rep_index))


def _velocity_loss_parameters(
    repetitions: tuple[VBTMetricResult, ...],
    current: VBTMetricResult,
    reference_rule: VBTVelocityLossReference,
    reference: VBTMetricResult,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("operation_id", VBT_VELOCITY_LOSS_OPERATION.stable_id),
        MetadataEntry("metric", current.metric.value),
        MetadataEntry(
            "velocity_metric_identity",
            current.observation.identity.semantic.metric_definition.stable_id,
        ),
        MetadataEntry("set_id", current.evidence.set_id.qualified),
        MetadataEntry("current_rep_id", current.evidence.rep_id.qualified),
        MetadataEntry("current_rep_index", current.evidence.rep_index),
        MetadataEntry(
            "reference_rule", _velocity_loss_reference_reference(reference_rule).stable_id
        ),
        MetadataEntry("reference_rep_id", reference.evidence.rep_id.qualified),
        MetadataEntry("reference_rep_index", reference.evidence.rep_index),
        MetadataEntry("reference_velocity_m_per_s", reference.value),
        MetadataEntry("current_velocity_m_per_s", current.value),
        MetadataEntry("external_load", canonical_json(current.evidence.external_load)),
        MetadataEntry(
            "repetition_ids", canonical_json(tuple(item.evidence.rep_id for item in repetitions))
        ),
        MetadataEntry(
            "equation", "100 * (reference_velocity - current_velocity) / reference_velocity"
        ),
    )


def _build_velocity_loss_observation(
    repetitions: tuple[VBTMetricResult, ...],
    current: VBTMetricResult,
    reference_rule: VBTVelocityLossReference,
    reference: VBTMetricResult,
    value: float,
    output_observation_id: InstanceIdentifier | None,
) -> ScientificMeasurementObservation:
    parameters = _velocity_loss_parameters(repetitions, current, reference_rule, reference)
    digest = canonical_hash(
        {"operation": VBT_VELOCITY_LOSS_OPERATION, "parameters": parameters, "value": value}
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"vbt-velocity-loss:{digest}"
    )
    source_identity = current.evidence.identity
    processing = StrengthProcessingIdentity(
        phase_definitions=(VBT_CONCENTRIC_PHASE_DEFINITION,),
        registered_operation=VBT_VELOCITY_LOSS_OPERATION,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=PERCENT,
        sign_convention=source_identity.acquisition.sign_convention,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = VBTMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"vbt-velocity-loss-{digest}",
            STRENGTH_REGISTRY_VERSION,
        ),
        semantic=replace(
            source_identity.semantic,
            construct=VBT_BAR_VELOCITY_CONSTRUCT,
            measurand=VBT_VELOCITY_LOSS_MEASURAND,
            metric_definition=VBT_VELOCITY_LOSS_METRIC,
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=VBT_VELOCITY_LOSS_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"vbt-velocity-loss:{digest}"),
        content_digest=canonical_hash({"value": value, "unit": PERCENT, "parameters": parameters}),
        media_type="application/vnd.dynamislm.vbt.velocity-loss",
        immutable=True,
    )
    base = current.observation.provenance
    for result in repetitions[1:]:
        base = _merge_provenance(base, result.observation.provenance)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"vbt-velocity-loss:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=VBT_VELOCITY_LOSS_OPERATION,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=tuple(item.observation.observation_id for item in repetitions),
        source_acquisition_ids=tuple(item.acquisition_id for item in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    edges = list(provenance.lineage_edges)
    for result in repetitions:
        for entity_id in (
            result.evidence.series.series_id,
            result.evidence.set_id,
            result.evidence.rep_id,
        ):
            edge = LineageEdge(
                entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
            )
            if edge not in edges:
                edges.append(edge)
        if result.phase.phase_id not in ():
            edge = LineageEdge(
                result.phase.phase_id.qualified,
                run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            )
            if edge not in edges:
                edges.append(edge)
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=current.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"vbt-velocity-loss:{digest}"),
            value=ScalarValue(value),
            unit=PERCENT,
            classification=ScientificClassification(ValueOrigin.DYNAMISLM_DERIVED, ()),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=replace(provenance, lineage_edges=tuple(edges)),
    )


def _validate_velocity_loss_result(result: VBTVelocityLossResult) -> None:
    _validate_same_set_repetitions(result.repetitions)
    if result.current not in result.repetitions:
        raise ValueError("velocity-loss current repetition is absent from its set")
    expected_reference = _select_velocity_loss_reference(
        result.repetitions, result.current, result.reference_rule
    )
    if result.reference_repetition != expected_reference:
        raise ValueError("velocity-loss reference repetition does not reproduce")
    if result.reference_repetition.value <= 0:
        raise ValueError("velocity-loss reference velocity must be positive")
    expected = (
        100.0
        * (result.reference_repetition.value - result.current.value)
        / result.reference_repetition.value
    )
    if _numeric_scalar(result.observation) != expected:
        raise ValueError("velocity-loss scalar does not reproduce from the reference rule")
    identity = result.observation.identity
    if not isinstance(identity, VBTMeasurementIdentity):
        raise ValueError("velocity-loss output requires VBT identity")
    if (
        identity.semantic.construct != VBT_BAR_VELOCITY_CONSTRUCT
        or identity.semantic.measurand != VBT_VELOCITY_LOSS_MEASURAND
        or identity.semantic.metric_definition != VBT_VELOCITY_LOSS_METRIC
    ):
        raise ValueError("velocity-loss output has the wrong identity")
    source_identity = result.current.evidence.identity
    if (
        identity.semantic.protocol_identity != source_identity.semantic.protocol_identity
        or identity.acquisition != source_identity.acquisition
    ):
        raise ValueError("velocity-loss output does not preserve protocol/acquisition identity")
    if (
        identity.processing.filtering != source_identity.processing.filtering
        or identity.processing.filtering_status != source_identity.processing.filtering_status
        or identity.processing.smoothing != source_identity.processing.smoothing
        or identity.processing.resampling != source_identity.processing.resampling
        or identity.processing.processing_state != StrengthProcessingState.DYNAMISLM_PROCESSED
    ):
        raise ValueError("velocity-loss output does not preserve processing identity")
    if (
        identity.processing.registered_operation != VBT_VELOCITY_LOSS_OPERATION
        or result.observation.result.unit != PERCENT
    ):
        raise ValueError("velocity-loss output has the wrong operation or unit")
    if result.observation.context != result.current.observation.context:
        raise ValueError("velocity-loss output context was rebound")
    parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
    if (
        parameters.get("reference_rule")
        != _velocity_loss_reference_reference(result.reference_rule).stable_id
        or parameters.get("reference_rep_id")
        != result.reference_repetition.evidence.rep_id.qualified
    ):
        raise ValueError("velocity-loss reference identity is not preserved")
    _require_vbt_output_lineage(
        result.observation,
        operation=VBT_VELOCITY_LOSS_OPERATION,
        parameters=identity.processing.method_parameters,
        source_entities=tuple(
            entity_id
            for item in result.repetitions
            for entity_id in (
                item.observation.observation_id,
                item.evidence.series.series_id,
                item.evidence.set_id,
                item.evidence.rep_id,
                item.phase.phase_id,
            )
        ),
    )


def calculate_velocity_loss(
    repetitions: tuple[VBTMetricResult, ...],
    reference_rule: VBTVelocityLossReference,
    *,
    current: VBTMetricResult | None = None,
    current_rep_index: int | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> VBTVelocityLossResult | RefusalResult:
    """Calculate a mechanical within-set loss with an explicit reference."""

    claim = "calculate VBT within-set velocity loss"
    try:
        require_tuple(repetitions, "repetitions")
        if not isinstance(reference_rule, VBTVelocityLossReference):
            raise ValueError("registered velocity-loss reference rule is required")
        _validate_same_set_repetitions(repetitions)
        if current is None:
            if type(current_rep_index) is not int:
                raise ValueError("current repetition or current_rep_index is required")
            matches = tuple(
                item for item in repetitions if item.evidence.rep_index == current_rep_index
            )
            if len(matches) != 1:
                raise ValueError("current_rep_index must identify exactly one repetition")
            current = matches[0]
        if current not in repetitions:
            raise ValueError("current repetition is absent from the supplied set")
        reference = _select_velocity_loss_reference(repetitions, current, reference_rule)
        if reference.value <= 0:
            raise ValueError("reference velocity must be positive")
        value = 100.0 * (reference.value - current.value) / reference.value
        observation = _build_velocity_loss_observation(
            repetitions, current, reference_rule, reference, value, output_observation_id
        )
        return VBTVelocityLossResult(observation, current, repetitions, reference_rule, reference)
    except (AttributeError, IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"one-set exact metric/load/rep reference: {exc}",),
            tuple(
                item.observation.observation_id
                for item in repetitions
                if isinstance(item, VBTMetricResult)
            ),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def refuse_velocity_loss_as_fatigue(
    *, observation_ids: tuple[InstanceIdentifier, ...] = ()
) -> RefusalResult:
    return _refusal(
        "interpret velocity loss as fatigue/readiness/neuromuscular state",
        (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        ("a registered physiological or fatigue inference model and applicable evidence",),
        observation_ids,
        refusal_class=RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED,
        safe_descriptions=(
            "the mechanical within-set velocity-loss quantity remains describable",
            "no fatigue, readiness, injury-risk, or physiological state is inferred",
        ),
    )


def _comparison_request(
    left: VBTMetricResult,
    right: VBTMetricResult,
    claim: str,
    request_id: InstanceIdentifier | None,
    requested_transformations: tuple[TransformationRequest, ...],
) -> ComparabilityRequest:
    return ComparabilityRequest(
        request_id=request_id
        or InstanceIdentifier(
            "comparability-request",
            canonical_hash(
                {
                    "left": left.observation.observation_id,
                    "right": right.observation.observation_id,
                    "claim": claim,
                }
            ).removeprefix("sha256:")[:24],
        ),
        left_observation_id=left.observation.observation_id,
        right_observation_id=right.observation.observation_id,
        claim=claim,
        requested_transformations=requested_transformations,
        material_dimensions=(
            "exercise",
            "protocol",
            "equipment",
            "load",
            "device",
            "attachment",
            "metric",
            "phase",
            "processing",
            "sampling",
        ),
    )


def _comparison_result(
    request: ComparabilityRequest,
    *,
    state: ComparabilityState,
    reason_codes: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    transformations: tuple[TransformationRequest, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result",
            f"{request.request_id.value}:{state.value.casefold()}",
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=reason_codes,
        conditions=conditions,
        transformations_required=transformations,
        missing_information=missing_information,
        rule_reference=VBT_FIXED_LOAD_COMPARABILITY_RULE,
        evidence_references=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _unresolved_comparison(
    request: ComparabilityRequest,
    missing_information: tuple[str, ...],
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:insufficient-information"
        ),
        request_id=request.request_id,
        state=ComparabilityState.INSUFFICIENT_INFORMATION,
        reason_codes=(ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,),
        conditions=(),
        transformations_required=request.requested_transformations,
        missing_information=missing_information,
        rule_reference=None,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.UNRESOLVED,
    )


def _comparison_timebase_key(timebase: StrengthTimebase) -> object:
    if timebase.kind is StrengthTimebaseKind.REGULAR:
        return (timebase.kind, timebase.sample_rate_hz)
    return (
        timebase.kind,
        tuple(right - left for left, right in pairwise(timebase.times_s)),
    )


def _comparison_acquisition_key(acquisition: StrengthAcquisitionIdentity) -> object:
    return {
        "device": acquisition.device,
        "provider": acquisition.provider,
        "sensor_modality": acquisition.sensor_modality,
        "attachment": acquisition.attachment_location,
        "sampling": acquisition.sampling,
        "unit": acquisition.unit,
        "physical_axis": acquisition.physical_axis,
        "reference_frame": acquisition.reference_frame,
        "sign_convention": acquisition.sign_convention,
        "timebase": (
            _comparison_timebase_key(acquisition.timebase)
            if acquisition.timebase is not None
            else None
        ),
    }


def compare_vbt_fixed_load(
    left: VBTMetricResult,
    right: VBTMetricResult,
    *,
    claim: str = "compare fixed-load VBT measurements longitudinally",
    request_id: InstanceIdentifier | None = None,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Adjudicate fixed-load VBT comparison without a caller override."""

    request = _comparison_request(left, right, claim, request_id, requested_transformations)
    try:
        _validate_vbt_metric_result(left)
        _validate_vbt_metric_result(right)
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        return _unresolved_comparison(request, (f"validated VBT metric observations: {exc}",))

    differences: list[tuple[str, str]] = []
    if left.observation.context.athlete_id != right.observation.context.athlete_id:
        differences.append(("ATHLETE_CONTEXT_MISMATCH", "athlete"))
    if left.metric is not right.metric:
        differences.append((ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH, "metric"))
    if left.evidence.external_load != right.evidence.external_load:
        differences.append(("LOAD_IDENTITY_MISMATCH", "physical_load_identity"))
    left_protocol = left.evidence.identity.semantic.protocol_identity
    right_protocol = right.evidence.identity.semantic.protocol_identity
    if left_protocol is None or right_protocol is None:
        return _unresolved_comparison(request, ("complete strength protocol identity",))
    missing: list[str] = []
    for label, result in (("left", left), ("right", right)):
        acquisition = result.evidence.identity.acquisition
        protocol = result.evidence.identity.semantic.protocol_identity
        processing = result.evidence.identity.processing
        if protocol is None:
            missing.append(f"{label} protocol identity")
            continue
        if acquisition.provider is None:
            missing.append(f"{label} acquisition provider")
        if acquisition.sensor_modality is StrengthSensorModality.UNKNOWN:
            missing.append(f"{label} sensor modality")
        if acquisition.attachment_location is None:
            missing.append(f"{label} attachment location")
        if acquisition.physical_axis is None:
            missing.append(f"{label} physical axis")
        if acquisition.reference_frame is None:
            missing.append(f"{label} reference frame")
        if acquisition.sign_convention is None:
            missing.append(f"{label} sign convention")
        if protocol.equipment is None or protocol.equipment_mode is StrengthEquipmentMode.UNKNOWN:
            missing.append(f"{label} equipment identity/mode")
        if processing.filtering_status is StrengthProcessingComponentStatus.UNKNOWN:
            missing.append(f"{label} filtering status")
        if processing.smoothing.status is StrengthProcessingComponentStatus.UNKNOWN:
            missing.append(f"{label} smoothing status")
        if processing.resampling.status is StrengthProcessingComponentStatus.UNKNOWN:
            missing.append(f"{label} resampling status")
    if missing:
        return _unresolved_comparison(request, tuple(dict.fromkeys(missing)))
    if left_protocol != right_protocol:
        differences.append((ComparabilityReasonCode.PROTOCOL_MISMATCH, "protocol"))
    if left.phase.phase_definition != right.phase.phase_definition:
        differences.append(("PHASE_DEFINITION_MISMATCH", "phase_definition"))
    if (
        left.phase.boundary_method != right.phase.boundary_method
        or left.phase.boundary_parameters != right.phase.boundary_parameters
    ):
        differences.append(("PHASE_BOUNDARY_METHOD_MISMATCH", "phase_boundary"))

    left_acquisition = left.evidence.identity.acquisition
    right_acquisition = right.evidence.identity.acquisition
    left_acq_key = _comparison_acquisition_key(left_acquisition)
    right_acq_key = _comparison_acquisition_key(right_acquisition)
    bridge_difference = False
    if left_acquisition.device != right_acquisition.device:
        differences.append((ComparabilityReasonCode.DEVICE_MISMATCH, "device"))
        bridge_difference = True
    if left_acquisition.provider != right_acquisition.provider:
        differences.append((ComparabilityReasonCode.PROVIDER_MISMATCH, "provider"))
        bridge_difference = True
    if left_acquisition.sensor_modality != right_acquisition.sensor_modality:
        differences.append((ComparabilityReasonCode.MODALITY_MISMATCH, "sensor_modality"))
        bridge_difference = True
    if left_acquisition.attachment_location != right_acquisition.attachment_location:
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "attachment_location"))
        bridge_difference = True
    if left_acquisition.sampling != right_acquisition.sampling:
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "sampling"))
        bridge_difference = True
    if _comparison_timebase_key(left.evidence.series.timebase) != _comparison_timebase_key(
        right.evidence.series.timebase
    ):
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "timebase"))
        bridge_difference = True
    if left_acq_key != right_acq_key:
        # Preserve a single granular bridge reason for differences such as
        # sign/frame or source processing that are not listed above.
        bridge_difference = True
    left_processing = left.evidence.identity.processing
    right_processing = right.evidence.identity.processing
    if (
        left_processing.filtering != right_processing.filtering
        or left_processing.filtering_status != right_processing.filtering_status
    ):
        differences.append((ComparabilityReasonCode.FILTERING_MISMATCH, "filtering"))
        bridge_difference = True
    if left_processing.method_parameters != right_processing.method_parameters:
        differences.append((ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "source_parameters"))
        bridge_difference = True
    if left_processing.smoothing != right_processing.smoothing:
        differences.append((ComparabilityReasonCode.SMOOTHING_MISMATCH, "smoothing"))
        bridge_difference = True
    if left_processing.resampling != right_processing.resampling:
        differences.append((ComparabilityReasonCode.RESAMPLING_MISMATCH, "resampling"))
        bridge_difference = True
    if left.evidence.series.processing_state != right.evidence.series.processing_state:
        differences.append(
            (ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "source_processing_state")
        )
        bridge_difference = True
    if (
        left.evidence.identity.version.software_version
        != right.evidence.identity.version.software_version
    ):
        differences.append((ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH, "software"))
        bridge_difference = True
    if (
        left.evidence.identity.version.hardware_firmware
        != right.evidence.identity.version.hardware_firmware
    ):
        differences.append((ComparabilityReasonCode.DEVICE_MISMATCH, "hardware_firmware"))
        bridge_difference = True
    if (
        left.evidence.identity.version.method_registry_version
        != right.evidence.identity.version.method_registry_version
        or left.evidence.identity.version.processing_method
        != right.evidence.identity.version.processing_method
    ):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "source_version"))
        bridge_difference = True
    if (
        left_acquisition.physical_axis != right_acquisition.physical_axis
        or left_acquisition.reference_frame != right_acquisition.reference_frame
        or left_acquisition.sign_convention != right_acquisition.sign_convention
    ):
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "axis_frame_sign"))
        bridge_difference = True

    hard_reasons = tuple(
        reason
        for reason, _ in differences
        if reason
        in {
            "ATHLETE_CONTEXT_MISMATCH",
            ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,
            "LOAD_IDENTITY_MISMATCH",
            ComparabilityReasonCode.PROTOCOL_MISMATCH,
            "PHASE_DEFINITION_MISMATCH",
            "PHASE_BOUNDARY_METHOD_MISMATCH",
        }
    )
    if hard_reasons:
        return _comparison_result(
            request,
            state=ComparabilityState.NOT_COMPARABLE,
            reason_codes=tuple(dict.fromkeys(hard_reasons)),
            conditions=(
                "the fixed-load longitudinal claim is blocked by a known identity mismatch",
            ),
            transformations=requested_transformations,
        )
    if differences or bridge_difference:
        return _comparison_result(
            request,
            state=ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            reason_codes=tuple(
                dict.fromkeys(
                    (ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,)
                    + tuple(reason for reason, _ in differences)
                    + (
                        (ComparabilityReasonCode.DEVICE_MISMATCH,)
                        if bridge_difference and not differences
                        else ()
                    )
                )
            ),
            conditions=(
                "a registered device/method agreement bridge is required before comparison",
            ),
            transformations=requested_transformations,
        )
    if requested_transformations:
        return _comparison_result(
            request,
            state=ComparabilityState.REQUIRES_TRANSFORMATION,
            reason_codes=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            conditions=(
                "the explicitly requested registered transformation must be applied first",
            ),
            transformations=requested_transformations,
        )
    return _comparison_result(request, state=ComparabilityState.COMPARABLE)


compare_vbt_fixed_loads = compare_vbt_fixed_load
assess_vbt_fixed_load_comparability = compare_vbt_fixed_load


# Discoverable aliases preserve the long scientific names in the primary API.
VBTVelocitySeriesEvidenceInput = VBTVelocitySeriesEvidence
MeanPropulsiveVelocityStatus = VBTPhaseAuthorityStatus
Measured1RM = MeasuredOneRepMax
Estimated1RM = EstimatedOneRepMax
LoadVelocityRelationship = LoadVelocityModel
calculate_mean_concentric_velocity_metric = calculate_mean_concentric_velocity
calculate_vbt_peak_velocity = calculate_peak_velocity
fit_individual_linear_load_velocity_model = fit_load_velocity_model
estimate_vbt_1rm = estimate_1rm_from_load_velocity_model
calculate_vbt_velocity_loss = calculate_velocity_loss
create_measured_1rm = build_measured_1rm
create_vbt_repetition_evidence = create_vbt_velocity_evidence
VBTRepetitionEvidence = VBTVelocitySeriesEvidence
VBTConcentricPhaseEvidence = VBTConcentricPhase
VBTSourceSeries = VBTVelocitySeries
VBTVelocityInput = VBTVelocitySeriesEvidence
calculate_mean_propulsive_velocity = refuse_mean_propulsive_velocity
calculate_vbt_mean_concentric_velocity = calculate_mean_concentric_velocity
calculate_vbt_mean_propulsive_velocity = refuse_mean_propulsive_velocity
compare_fixed_load_longitudinally = compare_vbt_fixed_load
compare_vbt_measurements = compare_vbt_fixed_load
fit_individual_load_velocity_model = fit_load_velocity_model
fit_load_velocity_relationship = fit_load_velocity_model
estimate_1rm = estimate_1rm_from_load_velocity_model
OneRepMaxMeasured = MeasuredOneRepMax
OneRepMaxEstimated = EstimatedOneRepMax
Measured1RMResult = MeasuredOneRepMax
Estimated1RMResult = EstimatedOneRepMax
LoadVelocityModelResult = LoadVelocityModel
VBTVelocityLoss = VBTVelocityLossResult


__all__ = [
    "RES66_SOFTWARE_VERSION",
    "SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017",
    "VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017",
    "Estimated1RM",
    "Estimated1RMResult",
    "EstimatedOneRepMax",
    "LoadVelocityModel",
    "LoadVelocityModelResult",
    "LoadVelocityRelationship",
    "MeanPropulsiveVelocityStatus",
    "Measured1RM",
    "Measured1RMResult",
    "MeasuredOneRepMax",
    "OneRepMaxEstimated",
    "OneRepMaxMeasured",
    "TerminalVelocityAssumption",
    "VBTConcentricPhase",
    "VBTConcentricPhaseEvidence",
    "VBTMetric",
    "VBTMetricResult",
    "VBTPhaseAuthorityStatus",
    "VBTRepetitionEvidence",
    "VBTSourceSeries",
    "VBTSuccessfulRepetition",
    "VBTVelocityInput",
    "VBTVelocityLoss",
    "VBTVelocityLossReference",
    "VBTVelocityLossResult",
    "VBTVelocitySeries",
    "VBTVelocitySeriesEvidence",
    "VBTVelocitySeriesEvidenceInput",
    "assess_vbt_fixed_load_comparability",
    "build_measured_1rm",
    "calculate_mean_concentric_velocity",
    "calculate_mean_concentric_velocity_metric",
    "calculate_mean_propulsive_velocity",
    "calculate_peak_velocity",
    "calculate_vbt_mean_concentric_velocity",
    "calculate_vbt_mean_propulsive_velocity",
    "calculate_vbt_metric",
    "calculate_vbt_peak_velocity",
    "calculate_vbt_velocity_loss",
    "calculate_velocity_loss",
    "compare_fixed_load_longitudinally",
    "compare_vbt_fixed_load",
    "compare_vbt_fixed_loads",
    "compare_vbt_measurements",
    "create_measured_1rm",
    "create_vbt_concentric_phase",
    "create_vbt_repetition_evidence",
    "create_vbt_velocity_evidence",
    "estimate_1rm",
    "estimate_1rm_from_load_velocity_model",
    "estimate_vbt_1rm",
    "fit_individual_linear_load_velocity_model",
    "fit_individual_load_velocity_model",
    "fit_load_velocity_model",
    "fit_load_velocity_relationship",
    "qualify_vbt_concentric_phase",
    "refuse_estimated_1rm_as_measured",
    "refuse_mean_propulsive_velocity",
    "refuse_velocity_loss_as_fatigue",
    "source_artifact_for_vbt_series",
]
