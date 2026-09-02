"""Registered CMJ supported-force, system-weight, and mass-derivation operations.

This module intentionally stops at the weighing boundary.  It does not select
movement events, integrate force, estimate a centre of mass, or emit a body
mass claim.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import stdev
from typing import TypeVar

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.cmj.acquisition import (
    AcquisitionArrangement,
    ArtifactHashScope,
    ArtifactStatus,
    ChannelRole,
    CMJAcquisitionIdentity,
    CMJChannelIdentity,
    CMJSourceArtifact,
    CombinationLineage,
    CombinationLineageKind,
    HashAlgorithm,
    ReferenceMetadata,
    ReferenceState,
    SignalProcessingState,
)
from dynamislm.measurement.cmj.identity import (
    CMJ_REGISTRY_VERSION,
    CMJ_TEST_FAMILY,
    CMJMeasurementIdentity,
    CMJSemanticIdentity,
)
from dynamislm.measurement.cmj.registry import (
    CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
    CMJ_DERIVED_COMPARABILITY_RULE,
    CMJ_DYNAMISLM_PROCESSING_SYSTEM,
    CMJ_EXPLICIT_WEIGHING_SEGMENT,
    CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT,
    CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND,
    CMJ_PHYSICAL_SYSTEM_MASS_METRIC,
    CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT,
    CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND,
    CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_METRIC,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_SYSTEM_WEIGHT_MEAN_FORCE,
    CMJ_SYSTEM_WEIGHT_MEASURAND,
    CMJ_SYSTEM_WEIGHT_METRIC,
    CMJ_SYSTEM_WEIGHT_OPERATION,
    CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND,
    CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
    CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_SCHEMA,
    KILOGRAM,
    METERS_PER_SECOND_SQUARED,
    NEWTON,
    RES44_DECISION_MASS_METROLOGY,
    STANDARD_GRAVITY_SOURCE,
)
from dynamislm.measurement.cmj.signal import (
    ExplicitTimebase,
    RawVerticalForceSignal,
    RegularTimebase,
    SignalTimebase,
)
from dynamislm.measurement.cmj.validation import (
    CMJValidationCode,
    ValidationStatus,
    validate_cmj_acquisition,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
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
    QualityStatus,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
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
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES35_SOFTWARE_VERSION = "dynamislm-res35-1.0.0"
RES44_SOFTWARE_VERSION = "dynamislm-res44-1.0.0"
STANDARD_GRAVITY_VALUE_M_PER_S2 = 9.80665


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")


def _stable_id(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, InstanceIdentifier):
        return value.qualified
    if isinstance(value, ScientificIdentifier):
        return value.stable_id
    if isinstance(value, RegistryReference):
        return value.stable_id
    if isinstance(value, UnitReference):
        return value.identifier.stable_id
    return None


def _unit_id(unit: UnitReference) -> str:
    return unit.identifier.stable_id


def _same_reference(left: object | None, right: object | None) -> bool:
    return _stable_id(left) == _stable_id(right)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProcessedVerticalForceSignal:
    """A new vertical-force series produced by a registered RES-35 operation."""

    signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    acquisition_identity_id: ScientificIdentifier
    source_signal_ids: tuple[InstanceIdentifier, ...]
    source_artifact_ids: tuple[InstanceIdentifier, ...]
    processing_run_id: InstanceIdentifier
    samples: tuple[float, ...]
    timebase: SignalTimebase
    channel_id: str
    unit: UnitReference
    physical_axis: RegistryReference
    reference_frame: RegistryReference
    sign_convention: SignConvention
    processing_state: SignalProcessingState = SignalProcessingState.SYSTEM_PROCESSED

    def __post_init__(self) -> None:
        require_tuple(self.source_signal_ids, "source_signal_ids")
        require_tuple(self.source_artifact_ids, "source_artifact_ids")
        require_tuple(self.samples, "samples")
        if len(self.source_signal_ids) != 2 or len(set(self.source_signal_ids)) != 2:
            raise ValueError("processed bilateral signal must name two distinct source signals")
        if len(self.source_artifact_ids) != 2 or len(set(self.source_artifact_ids)) != 2:
            raise ValueError("processed bilateral signal must name two distinct source artifacts")
        if not self.samples:
            raise ValueError("processed vertical-force signal must contain samples")
        for sample in self.samples:
            _finite(sample, "processed vertical-force sample")
        if not isinstance(self.timebase, RegularTimebase | ExplicitTimebase):
            raise ValueError("processed signal requires a registered timebase")
        if not self.channel_id.strip():
            raise ValueError("processed signal channel_id must not be empty")
        if self.processing_state is not SignalProcessingState.SYSTEM_PROCESSED:
            raise ValueError("processed vertical-force signal must be SYSTEM_PROCESSED")

    def canonical_content_digest(self) -> str:
        """Hash the exact processed sample/timebase representation."""

        return canonical_hash({"samples": self.samples, "timebase": self.timebase})


@register_serializable_type
@dataclass(frozen=True, slots=True)
class WeighingSegment:
    """An explicitly supplied half-open sample-index interval used for weighing."""

    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    start_index: int
    end_index: int
    selection_method: RegistryReference = CMJ_EXPLICIT_WEIGHING_SEGMENT
    selection_parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.start_index, bool) or not isinstance(self.start_index, int):
            raise ValueError("start_index must be an integer")
        if isinstance(self.end_index, bool) or not isinstance(self.end_index, int):
            raise ValueError("end_index must be an integer")
        if self.start_index < 0 or self.end_index <= self.start_index:
            raise ValueError("weighing segment must satisfy 0 <= start_index < end_index")
        if self.selection_method.stable_id != CMJ_EXPLICIT_WEIGHING_SEGMENT.stable_id:
            raise ValueError("selection_method must be the registered explicit segment method")
        require_tuple(self.selection_parameters, "selection_parameters")

    @property
    def interval_semantics(self) -> str:
        return "[start_index, end_index)"

    @property
    def sample_count(self) -> int:
        return self.end_index - self.start_index


@register_serializable_type
@dataclass(frozen=True, slots=True)
class WeighingBaselineQC:
    """Descriptive within-window values; no universal accept/reject threshold."""

    sample_count: int
    duration_s: float
    mean_force_n: float
    standard_deviation_n: float
    range_n: float
    acceptability_adjudicated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int):
            raise ValueError("sample_count must be an integer")
        if self.sample_count < 2:
            raise ValueError("sample_count must be at least two")
        for field_name, value in (
            ("duration_s", self.duration_s),
            ("mean_force_n", self.mean_force_n),
            ("standard_deviation_n", self.standard_deviation_n),
            ("range_n", self.range_n),
        ):
            _finite(value, field_name)
        if self.duration_s < 0 or self.standard_deviation_n < 0 or self.range_n < 0:
            raise ValueError("duration, standard deviation, and range must not be negative")
        if not isinstance(self.acceptability_adjudicated, bool):
            raise ValueError("acceptability_adjudicated must be boolean")

    @property
    def quality_flags(self) -> tuple[str, ...]:
        return (
            "QC_DESCRIBED",
            "QC_ACCEPTABILITY_ADJUDICATED"
            if self.acceptability_adjudicated
            else "QC_ACCEPTABILITY_NOT_ADJUDICATED",
        )


class GravityReferenceType(StrEnum):
    STANDARD_GRAVITY = "STANDARD_GRAVITY"
    LOCAL_GRAVITATIONAL_ACCELERATION = "LOCAL_GRAVITATIONAL_ACCELERATION"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class GravityReference:
    """Explicit gravitational acceleration/reference for one named mass operation."""

    value_m_per_s2: float
    reference_type: GravityReferenceType
    source: RegistryReference
    unit: UnitReference = METERS_PER_SECOND_SQUARED
    uncertainty: UncertaintyMetadata = field(default_factory=UncertaintyMetadata)

    def __post_init__(self) -> None:
        _finite(self.value_m_per_s2, "gravity value")
        if self.value_m_per_s2 <= 0:
            raise ValueError("gravity value must be positive")
        if not isinstance(self.reference_type, GravityReferenceType):
            raise ValueError("reference_type must be a registered GravityReferenceType")
        if _unit_id(self.unit) != _unit_id(METERS_PER_SECOND_SQUARED):
            raise ValueError("gravity must be represented in m/s^2")
        if self.reference_type is GravityReferenceType.STANDARD_GRAVITY and (
            self.value_m_per_s2 != STANDARD_GRAVITY_VALUE_M_PER_S2
            or self.source.stable_id != STANDARD_GRAVITY_SOURCE.stable_id
        ):
            raise ValueError(
                "STANDARD_GRAVITY must use the registered conventional value and source"
            )

    @property
    def is_standard(self) -> bool:
        return self.reference_type is GravityReferenceType.STANDARD_GRAVITY

    @property
    def is_local(self) -> bool:
        return self.reference_type is GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION


STANDARD_GRAVITY = GravityReference(
    value_m_per_s2=STANDARD_GRAVITY_VALUE_M_PER_S2,
    reference_type=GravityReferenceType.STANDARD_GRAVITY,
    source=STANDARD_GRAVITY_SOURCE,
    uncertainty=UncertaintyMetadata(
        status=UncertaintyStatus.NOT_ASSESSED,
        description="Conventional standard acceleration of gravity; not a local-gravity estimate.",
    ),
)


def _validate_mass_result_provenance(
    observation: ScientificMeasurementObservation,
    gravity: GravityReference,
    *,
    operation: RegistryReference,
    measurand: RegistryReference,
    source_weight_observation_id: InstanceIdentifier,
) -> None:
    """Ensure the wrapper fields agree with the registered derived observation."""

    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        raise ValueError("mass result requires a CMJ measurement identity")
    if source_weight_observation_id.instance_type != "observation":
        raise ValueError("mass result source must be an observation identifier")
    parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
    expected_parameters = {
        "operation_id": operation.stable_id,
        "operation_version": operation.identifier.version,
        "output_measurand": measurand.stable_id,
        "source_weight_observation_id": source_weight_observation_id.qualified,
        "gravity_value_m_per_s2": gravity.value_m_per_s2,
        "gravity_unit": _unit_id(gravity.unit),
        "gravity_reference_type": gravity.reference_type.value,
        "gravity_source": gravity.source.stable_id,
        "gravity_uncertainty_status": gravity.uncertainty.status.value,
        "gravity_uncertainty_description": gravity.uncertainty.description or "not provided",
    }
    if any(parameters.get(key) != value for key, value in expected_parameters.items()):
        raise ValueError("mass result wrapper and observation gravity/procedure metadata disagree")
    matching_runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_observation_id == observation.observation_id
        and run.method.stable_id == operation.stable_id
    )
    if len(matching_runs) != 1:
        raise ValueError("mass result requires one matching RES-44 processing run")
    processing_run = matching_runs[0]
    if (
        processing_run.parameters != identity.processing.method_parameters
        or processing_run.software_version != RES44_SOFTWARE_VERSION
    ):
        raise ValueError("mass result processing provenance does not match its identity")
    if not any(
        edge.from_id == source_weight_observation_id.qualified
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        for edge in observation.provenance.lineage_edges
    ):
        raise ValueError("mass result is missing exact SYSTEM_WEIGHT lineage")
    if not any(
        edge.from_id == gravity.source.stable_id
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.SUPPORTED_BY
        for edge in observation.provenance.lineage_edges
    ):
        raise ValueError("mass result is missing exact gravity support lineage")
    if gravity.source not in observation.provenance.metrological_traceability:
        raise ValueError("mass result is missing exact gravity metrological traceability")
    if not any(
        edge.from_id == RES44_DECISION_MASS_METROLOGY.stable_id
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.SUPPORTED_BY
        for edge in observation.provenance.lineage_edges
    ):
        raise ValueError("mass result is missing RES-44 decision support lineage")
    if not any(
        evidence.reference == RES44_DECISION_MASS_METROLOGY
        for evidence in observation.provenance.evidence_references
    ):
        raise ValueError("mass result is missing RES-44 decision evidence")


type ForceSignal = RawVerticalForceSignal | ProcessedVerticalForceSignal


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJForceInput:
    """All linked objects required to operate on one CMJ force series."""

    observation: ScientificMeasurementObservation
    identity: CMJMeasurementIdentity
    signal: ForceSignal
    source_artifact: CMJSourceArtifact
    acquisition: AcquisitionRecord

    @property
    def artifact(self) -> CMJSourceArtifact:
        return self.source_artifact


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TotalSupportedForceResult:
    """A total supported vertical-force series and its complete observation lineage."""

    observation: ScientificMeasurementObservation
    signal: ForceSignal
    source_artifact: CMJSourceArtifact
    acquisition: AcquisitionRecord

    @property
    def artifact(self) -> CMJSourceArtifact:
        return self.source_artifact

    def as_force_input(self) -> CMJForceInput:
        identity = self.observation.identity
        if not isinstance(identity, CMJMeasurementIdentity):
            raise ValueError("total-force observation must have a CMJ measurement identity")
        return CMJForceInput(
            observation=self.observation,
            identity=identity,
            signal=self.signal,
            source_artifact=self.source_artifact,
            acquisition=self.acquisition,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SystemWeightResult:
    """A scalar supported-system force estimated from one weighing segment."""

    observation: ScientificMeasurementObservation
    segment: WeighingSegment
    qc: WeighingBaselineQC

    @property
    def value_n(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("system-weight result does not contain a numeric scalar")
        return float(value.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PhysicalSystemMassResult:
    """A scalar supported-system mass derived with applicable local gravity."""

    observation: ScientificMeasurementObservation
    gravity_reference: GravityReference
    source_system_weight_observation_id: InstanceIdentifier

    def __post_init__(self) -> None:
        identity = self.observation.identity
        if not isinstance(identity, CMJMeasurementIdentity):
            raise ValueError("physical-system-mass result requires a CMJ measurement identity")
        if not self.gravity_reference.is_local:
            raise ValueError(
                "physical-system-mass result requires LOCAL_GRAVITATIONAL_ACCELERATION"
            )
        if identity.semantic.measurand.stable_id != CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND.stable_id:
            raise ValueError("physical-system-mass result has the wrong measurand identity")
        if (
            identity.semantic.metric_definition.stable_id
            != CMJ_PHYSICAL_SYSTEM_MASS_METRIC.stable_id
        ):
            raise ValueError("physical-system-mass result has the wrong metric identity")
        if (
            identity.processing.registered_operation is None
            or identity.processing.registered_operation.stable_id
            != CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT.stable_id
        ):
            raise ValueError("physical-system-mass result has the wrong operation identity")
        _validate_mass_result_provenance(
            self.observation,
            self.gravity_reference,
            operation=CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT,
            measurand=CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND,
            source_weight_observation_id=self.source_system_weight_observation_id,
        )
        if self.source_system_weight_observation_id == self.observation.observation_id:
            raise ValueError("mass result source SYSTEM_WEIGHT must differ from output observation")

    @property
    def value_kg(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("physical-system-mass result does not contain a numeric scalar")
        return float(value.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StandardGravityMassEquivalentResult:
    """A scalar ``W/g_n`` reference quantity, not automatically physical mass."""

    observation: ScientificMeasurementObservation
    gravity_reference: GravityReference
    source_system_weight_observation_id: InstanceIdentifier

    def __post_init__(self) -> None:
        identity = self.observation.identity
        if not isinstance(identity, CMJMeasurementIdentity):
            raise ValueError(
                "standard-gravity-mass-equivalent result requires a CMJ measurement identity"
            )
        if not self.gravity_reference.is_standard:
            raise ValueError("standard-gravity-mass-equivalent result requires STANDARD_GRAVITY")
        if (
            identity.semantic.measurand.stable_id
            != CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND.stable_id
        ):
            raise ValueError("standard-gravity-mass-equivalent result has the wrong measurand")
        if (
            identity.semantic.metric_definition.stable_id
            != CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_METRIC.stable_id
        ):
            raise ValueError("standard-gravity-mass-equivalent result has the wrong metric")
        if (
            identity.processing.registered_operation is None
            or identity.processing.registered_operation.stable_id
            != CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT.stable_id
        ):
            raise ValueError(
                "standard-gravity-mass-equivalent result has the wrong operation identity"
            )
        _validate_mass_result_provenance(
            self.observation,
            self.gravity_reference,
            operation=CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT,
            measurand=CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND,
            source_weight_observation_id=self.source_system_weight_observation_id,
        )
        if self.source_system_weight_observation_id == self.observation.observation_id:
            raise ValueError("mass result source SYSTEM_WEIGHT must differ from output observation")

    @property
    def value_kg(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError(
                "standard-gravity-mass-equivalent result does not contain a numeric scalar"
            )
        return float(value.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJDerivedComparabilityRequest:
    """Claim-relative pair request for RES-44 derived observations."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    left_identity: MeasurementIdentity
    right_identity: MeasurementIdentity
    claim: str
    left_segment: WeighingSegment | None = None
    right_segment: WeighingSegment | None = None
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.claim, "claim")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("comparability requires two distinct observations")
        require_tuple(self.requested_transformations, "requested_transformations")


_T = TypeVar("_T")


def _append_unique(values: tuple[_T, ...], additions: tuple[_T, ...]) -> tuple[_T, ...]:
    result = list(values)
    for addition in additions:
        if addition not in result:
            result.append(addition)
    return tuple(result)


def _merge_provenance(left: Provenance, right: Provenance) -> Provenance:
    """Merge two immutable source DAGs without dropping either source history."""

    source_artifacts = _append_unique(left.source_artifacts, right.source_artifacts)
    acquisitions = _append_unique(left.acquisitions, right.acquisitions)
    processing_runs = _append_unique(left.processing_runs, right.processing_runs)
    lineage_edges = _append_unique(left.lineage_edges, right.lineage_edges)
    evidence_references = _append_unique(left.evidence_references, right.evidence_references)
    metrological_traceability = _append_unique(
        left.metrological_traceability, right.metrological_traceability
    )
    return Provenance(
        provenance_id=left.provenance_id,
        source_artifacts=tuple(
            sorted(source_artifacts, key=lambda item: item.artifact_id.qualified)
        ),
        acquisitions=tuple(sorted(acquisitions, key=lambda item: item.acquisition_id.qualified)),
        processing_runs=tuple(
            sorted(processing_runs, key=lambda item: item.processing_run_id.qualified)
        ),
        lineage_edges=tuple(
            sorted(
                lineage_edges,
                key=lambda item: (item.from_id, item.to_id, item.relation.value),
            )
        ),
        evidence_references=tuple(
            sorted(evidence_references, key=lambda item: item.reference.stable_id)
        ),
        metrological_traceability=tuple(
            sorted(metrological_traceability, key=lambda item: item.stable_id)
        ),
        recorded_at=left.recorded_at or right.recorded_at,
    )


def _provenance_with_run(
    base: Provenance,
    *,
    processing_run: ProcessingRun,
    output_observation_id: InstanceIdentifier,
    source_observation_ids: tuple[InstanceIdentifier, ...],
    source_acquisition_ids: tuple[InstanceIdentifier, ...],
    output_artifacts: tuple[SourceArtifact, ...] = (),
    output_acquisitions: tuple[AcquisitionRecord, ...] = (),
    produced_artifact_ids: tuple[InstanceIdentifier, ...] = (),
    supported_by: tuple[RegistryReference, ...] = (),
    evidence_references: tuple[EvidenceReference, ...] = (),
    metrological_traceability: tuple[RegistryReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> Provenance:
    artifacts = _append_unique(base.source_artifacts, output_artifacts)
    acquisitions = _append_unique(base.acquisitions, output_acquisitions)
    runs = _append_unique(base.processing_runs, (processing_run,))
    evidence = _append_unique(base.evidence_references, evidence_references)
    traceability = _append_unique(base.metrological_traceability, metrological_traceability)
    edges = list(base.lineage_edges)
    for source_observation_id in source_observation_ids:
        edge = LineageEdge(
            source_observation_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for source_artifact_id in processing_run.source_artifact_ids:
        edge = LineageEdge(
            source_artifact_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for source_acquisition_id in source_acquisition_ids:
        edge = LineageEdge(
            source_acquisition_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    for output_artifact in output_artifacts:
        edge = LineageEdge(
            output_artifact.artifact_id.qualified,
            next(
                acquisition.acquisition_id.qualified
                for acquisition in output_acquisitions
                if acquisition.source_artifact_id == output_artifact.artifact_id
            ),
            LineageRelation.ACQUIRED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    for artifact_id in produced_artifact_ids:
        edge = LineageEdge(
            processing_run.processing_run_id.qualified,
            artifact_id.qualified,
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
        output_observation_id.qualified,
        LineageRelation.PRODUCED,
    )
    if output_edge not in edges:
        edges.append(output_edge)
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_observation_id.value),
        source_artifacts=artifacts,
        acquisitions=acquisitions,
        processing_runs=runs,
        lineage_edges=tuple(edges),
        evidence_references=evidence,
        metrological_traceability=traceability,
        recorded_at=recorded_at if recorded_at is not None else base.recorded_at,
    )


def _refusal(
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    safe_descriptions: tuple[str, ...] = (
        "the source acquisition and any independently valid upstream observation remain "
        "describable",
        "no unsupported CMJ performance or body-mass claim is emitted",
    ),
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    codes = tuple(code.value for code in reason_codes)
    refusal_key = canonical_hash(
        {
            "blocked_claim": blocked_claim,
            "reason_codes": codes,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res35:{refusal_key}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions,
        observation_ids=observation_ids,
    )


def _input_observation_ids(*inputs: CMJForceInput) -> tuple[InstanceIdentifier, ...]:
    return tuple(input_value.observation.observation_id for input_value in inputs)


def _input_common_refusal(input_value: CMJForceInput, claim: str) -> RefusalResult | None:
    signal = input_value.signal
    identity = input_value.identity
    artifact = input_value.source_artifact
    acquisition = input_value.acquisition
    acquisition_identity = identity.acquisition
    observation = input_value.observation
    observation_id = observation.observation_id
    if observation.identity != identity:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("observation.identity",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if signal.acquisition_identity_id != identity.identity_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("signal.acquisition_identity_id",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if signal.source_artifact_id != artifact.artifact_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("signal.source_artifact_id",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if identity.acquisition.raw_artifact != artifact.artifact_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("acquisition.raw_artifact",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if acquisition.acquisition_id != signal.acquisition_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("acquisition.acquisition_id",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if acquisition.source_artifact_id != artifact.artifact_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("acquisition.source_artifact_id",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if acquisition.sensor_channel != signal.channel_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("acquisition.sensor_channel",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if artifact.acquisition_id != signal.acquisition_id:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("source_artifact.acquisition_id",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not _same_reference(acquisition.device, acquisition_identity.device):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("acquisition.device",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if not artifact.immutable or artifact.status is not ArtifactStatus.VERIFIED:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("verified immutable source artifact",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    provenance_artifacts = {item.artifact_id for item in observation.provenance.source_artifacts}
    provenance_acquisitions = {item.acquisition_id for item in observation.provenance.acquisitions}
    if artifact.artifact_id not in provenance_artifacts or acquisition.acquisition_id not in (
        provenance_acquisitions
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("observation.provenance source artifact/acquisition",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    provenance_edges = observation.provenance.lineage_edges
    has_artifact_acquisition_edge = any(
        edge.from_id == artifact.artifact_id.qualified
        and edge.to_id == acquisition.acquisition_id.qualified
        and edge.relation is LineageRelation.ACQUIRED_AS
        for edge in provenance_edges
    )
    if not has_artifact_acquisition_edge:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("artifact-to-acquisition provenance edge",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if isinstance(signal, RawVerticalForceSignal):
        has_acquisition_observation_edge = any(
            edge.from_id == acquisition.acquisition_id.qualified
            and edge.to_id == observation_id.qualified
            and edge.relation is LineageRelation.PRODUCED
            for edge in provenance_edges
        )
        if not has_acquisition_observation_edge:
            return _refusal(
                claim,
                (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
                ("acquisition-to-observation provenance edge",),
                observation_ids=(observation_id,),
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
    else:
        has_processed_observation = any(
            run.output_observation_id == observation_id
            and any(
                edge.from_id == run.processing_run_id.qualified
                and edge.to_id == observation_id.qualified
                and edge.relation is LineageRelation.PRODUCED
                for edge in provenance_edges
            )
            and any(
                edge.from_id == run.processing_run_id.qualified
                and edge.to_id == signal.source_artifact_id.qualified
                and edge.relation is LineageRelation.PRODUCED
                for edge in provenance_edges
            )
            and run.processing_run_id == signal.processing_run_id
            and run.source_artifact_ids == signal.source_artifact_ids
            and all(
                source_artifact_id in provenance_artifacts
                for source_artifact_id in signal.source_artifact_ids
            )
            and all(
                any(
                    acquisition_record.source_artifact_id == source_artifact_id
                    and any(
                        edge.from_id == acquisition_record.acquisition_id.qualified
                        and edge.to_id == run.processing_run_id.qualified
                        and edge.relation is LineageRelation.PROCESSED_AS
                        for edge in provenance_edges
                    )
                    for acquisition_record in observation.provenance.acquisitions
                )
                for source_artifact_id in run.source_artifact_ids
            )
            for run in observation.provenance.processing_runs
        )
        if not has_processed_observation:
            return _refusal(
                claim,
                (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
                ("processed acquisition-to-observation provenance path",),
                observation_ids=(observation_id,),
                refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            )
    if isinstance(signal, RawVerticalForceSignal):
        validation = validate_cmj_acquisition(identity, signal, artifact)
        if validation.status is not ValidationStatus.VALID:
            if any(
                issue.code
                in {
                    CMJValidationCode.INVALID_TIMEBASE,
                    CMJValidationCode.TIME_COUNT_MISMATCH,
                    CMJValidationCode.NONFINITE_TIME,
                    CMJValidationCode.DUPLICATE_TIME,
                    CMJValidationCode.NON_MONOTONIC_TIME,
                    CMJValidationCode.DECLARED_SAMPLE_RATE_MISMATCH,
                    CMJValidationCode.MISSING_TIMEBASE,
                    CMJValidationCode.TIMEBASE_KIND_MISMATCH,
                }
                for issue in validation.issues
            ):
                return _refusal(
                    claim,
                    (RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,),
                    ("valid source signal timebase",),
                    observation_ids=(observation_id,),
                    refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
                )
            if any(
                issue.code is CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH
                for issue in validation.issues
            ):
                return _refusal(
                    claim,
                    (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
                    ("signal and acquisition semantics must agree",),
                    observation_ids=(observation_id,),
                    refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
                )
            if any(
                issue.code
                in {
                    CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH,
                    CMJValidationCode.MISSING_AXIS,
                    CMJValidationCode.MISSING_REFERENCE_FRAME,
                    CMJValidationCode.MISSING_SIGN_CONVENTION,
                    CMJValidationCode.UNREGISTERED_AXIS,
                    CMJValidationCode.UNREGISTERED_REFERENCE_FRAME,
                }
                for issue in validation.issues
            ):
                return _refusal(
                    claim,
                    (RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED,),
                    ("consistent registered axis/frame/sign semantics",),
                    observation_ids=(observation_id,),
                    refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
                )
            from dynamislm.measurement.cmj.refusal import refusal_for_cmj_validation

            return refusal_for_cmj_validation(
                validation,
                blocked_claim=claim,
                observation_ids=(observation_id,),
            )
    elif signal.processing_state is SignalProcessingState.UNKNOWN:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("processed signal processing_state",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        signal.unit is None
        or acquisition_identity.unit is None
        or not _same_reference(signal.unit, acquisition_identity.unit)
        or signal.physical_axis is None
        or acquisition_identity.physical_axis is None
        or not _same_reference(signal.physical_axis, acquisition_identity.physical_axis)
        or signal.reference_frame is None
        or acquisition_identity.reference_frame is None
        or not _same_reference(signal.reference_frame, acquisition_identity.reference_frame)
        or signal.sign_convention is None
        or acquisition_identity.sign_convention is None
        or signal.sign_convention != acquisition_identity.sign_convention
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("signal and acquisition force semantics",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if artifact.content_digest != signal.canonical_content_digest():
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("source artifact content digest",),
            observation_ids=(observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _force_semantics_refusal(input_value: CMJForceInput, claim: str) -> RefusalResult | None:
    signal = input_value.signal
    identity = input_value.identity
    acquisition = identity.acquisition
    unit = signal.unit
    if unit is None or _unit_id(unit) != _unit_id(NEWTON):
        return _refusal(
            claim,
            (RefusalReasonCode.FORCE_UNIT_TRANSFORMATION_REQUIRED,),
            ("canonical force unit N",),
            observation_ids=(input_value.observation.observation_id,),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    axis = signal.physical_axis or acquisition.physical_axis
    frame = signal.reference_frame or acquisition.reference_frame
    sign = signal.sign_convention or acquisition.sign_convention
    if (
        axis is None
        or axis.identifier.object_type != "axis"
        or not _is_vertical_axis(axis)
        or frame is None
        or frame.identifier.object_type != "reference-frame"
        or sign is None
        or sign.reference is None
        or sign.positive_direction != "upward"
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED,),
            ("registered vertical axis, reference frame, and upward-positive sign convention",),
            observation_ids=(input_value.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if signal.timebase is None:
        return _refusal(
            claim,
            (RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,),
            ("registered signal timebase",),
            observation_ids=(input_value.observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    timebase_refusal = _timebase_refusal(signal)
    if timebase_refusal is not None:
        return _refusal(
            claim,
            (RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,),
            ("valid signal timebase",),
            observation_ids=(input_value.observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if signal.processing_state is SignalProcessingState.UNKNOWN:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("known signal processing state",),
            observation_ids=(input_value.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _is_vertical_axis(axis: RegistryReference) -> bool:
    key = axis.identifier.key.lower()
    return "vertical" in key or key in {"z", "z-axis"}


def _timebase_refusal(signal: ForceSignal) -> str | None:
    timebase = signal.timebase
    if timebase is None:
        return "missing"
    if isinstance(timebase, RegularTimebase):
        return None if timebase.sample_rate_hz > 0 else "invalid"
    if not isinstance(timebase, ExplicitTimebase):
        return "invalid"
    if len(timebase.times_s) != len(signal.samples):
        return "count"
    previous: float | None = None
    for time in timebase.times_s:
        if not math.isfinite(time) or (previous is not None and time <= previous):
            return "invalid"
        previous = time
    return None


def _timebase_equal(left: SignalTimebase, right: SignalTimebase) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, RegularTimebase) and isinstance(right, RegularTimebase):
        return left == right
    if isinstance(left, ExplicitTimebase) and isinstance(right, ExplicitTimebase):
        return left.times_s == right.times_s
    return False


def _context_key(context: ObservationContext) -> tuple[object, ...]:
    return (
        context.athlete_id,
        context.session_id,
        context.test_instance_id,
        context.trial_id,
        context.population_context,
        context.environment,
        context.context_metadata,
    )


def _protocol_key(identity: CMJMeasurementIdentity) -> str:
    return canonical_hash(identity.semantic.protocol_identity)


def _input_axis(input_value: CMJForceInput) -> RegistryReference | None:
    return input_value.signal.physical_axis or input_value.identity.acquisition.physical_axis


def _input_frame(input_value: CMJForceInput) -> RegistryReference | None:
    return input_value.signal.reference_frame or input_value.identity.acquisition.reference_frame


def _input_sign(input_value: CMJForceInput) -> SignConvention | None:
    return input_value.signal.sign_convention or input_value.identity.acquisition.sign_convention


def _required_axis(input_value: CMJForceInput) -> RegistryReference:
    axis = _input_axis(input_value)
    if axis is None:
        raise ValueError("registered force axis is required")
    return axis


def _required_frame(input_value: CMJForceInput) -> RegistryReference:
    frame = _input_frame(input_value)
    if frame is None:
        raise ValueError("registered force reference frame is required")
    return frame


def _required_sign(input_value: CMJForceInput) -> SignConvention:
    sign = _input_sign(input_value)
    if sign is None:
        raise ValueError("explicit force sign convention is required")
    return sign


def _required_timebase(input_value: CMJForceInput) -> SignalTimebase:
    timebase = input_value.signal.timebase
    if timebase is None:
        raise ValueError("registered signal timebase is required")
    return timebase


def _signal_sampling(
    identity: CMJAcquisitionIdentity,
    signal: ForceSignal,
) -> SamplingCharacteristics:
    base = identity.sampling
    rate = base.frequency_hz if base is not None else None
    if rate is None and isinstance(signal.timebase, RegularTimebase):
        rate = signal.timebase.sample_rate_hz
    sample_format = base.sample_format if base is not None else None
    if signal.channel_id is None:
        raise ValueError("force signal channel_id is required for processed output")
    return SamplingCharacteristics(rate, (signal.channel_id,), sample_format)


def _derived_semantic(
    source: CMJMeasurementIdentity,
    *,
    measurand: RegistryReference,
    metric: RegistryReference,
) -> CMJSemanticIdentity:
    return CMJSemanticIdentity(
        construct=CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
        test_family=CMJ_TEST_FAMILY,
        protocol=source.semantic.protocol,
        measurand=measurand,
        metric_definition=metric,
        protocol_identity=source.semantic.protocol_identity,
    )


def _derived_identity(
    source: CMJMeasurementIdentity,
    *,
    identity_id: ScientificIdentifier,
    measurand: RegistryReference,
    metric: RegistryReference,
    processing: ProcessingIdentity,
    processing_method: RegistryReference,
    software_version: str = RES35_SOFTWARE_VERSION,
) -> CMJMeasurementIdentity:
    return CMJMeasurementIdentity(
        identity_id=identity_id,
        semantic=_derived_semantic(source, measurand=measurand, metric=metric),
        acquisition=source.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=processing_method,
            method_registry_version=CMJ_REGISTRY_VERSION,
            software_version=software_version,
            hardware_firmware=source.version.hardware_firmware,
        ),
    )


def _input_identity_key(input_value: CMJForceInput) -> tuple[str, str, str]:
    signal_id = input_value.signal.signal_id.qualified
    artifact_id = input_value.source_artifact.artifact_id.qualified
    observation_id = input_value.observation.observation_id.qualified
    return signal_id, artifact_id, observation_id


def _output_digest(*inputs: CMJForceInput, operation: RegistryReference) -> str:
    return canonical_hash(
        {
            "operation": operation.stable_id,
            "inputs": tuple(_input_identity_key(item) for item in inputs),
        }
    ).removeprefix("sha256:")[:24]


def _make_output_acquisition_identity(
    source: CMJForceInput,
    *,
    output_artifact_id: InstanceIdentifier,
    output_acquisition_id: InstanceIdentifier,
    output_channel_id: str,
    combination_lineage: CombinationLineage,
    processing_state: SignalProcessingState,
) -> CMJAcquisitionIdentity:
    source_acquisition = source.identity.acquisition
    return CMJAcquisitionIdentity(
        device=CMJ_DYNAMISLM_PROCESSING_SYSTEM,
        raw_artifact=output_artifact_id,
        sensor_channel=output_channel_id,
        sampling=_signal_sampling(source_acquisition, source.signal),
        calibration_reference=None,
        hardware_firmware=None,
        measuring_system=CMJ_DYNAMISLM_PROCESSING_SYSTEM,
        arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED,
        acquisition_instance_id=output_acquisition_id,
        channel=CMJChannelIdentity(output_channel_id, ChannelRole.PRECOMBINED_VERTICAL_FORCE),
        available_channels=(
            CMJChannelIdentity(output_channel_id, ChannelRole.PRECOMBINED_VERTICAL_FORCE),
        ),
        physical_axis=_required_axis(source),
        reference_frame=_required_frame(source),
        unit=NEWTON,
        sign_convention=_required_sign(source),
        timebase=source_acquisition.timebase,
        acquisition_software_version=RES35_SOFTWARE_VERSION,
        acquisition_timestamp=source_acquisition.acquisition_timestamp,
        calibration=ReferenceMetadata(ReferenceState.NOT_PROVIDED),
        zeroing=ReferenceMetadata(ReferenceState.NOT_PROVIDED),
        processing_state=processing_state,
        combination_lineage=combination_lineage,
    )


def _processed_artifact(
    signal: ProcessedVerticalForceSignal,
    acquisition_id: InstanceIdentifier,
) -> CMJSourceArtifact:
    return CMJSourceArtifact(
        artifact_id=signal.source_artifact_id,
        content_digest=signal.canonical_content_digest(),
        media_type="application/vnd.dynamislm.cmj.total-supported-vertical-force-series",
        immutable=True,
        hash_algorithm=HashAlgorithm.SHA256,
        hash_scope=ArtifactHashScope.CANONICAL_SIGNAL_REPRESENTATION,
        status=ArtifactStatus.VERIFIED,
        acquisition_id=acquisition_id,
    )


def _build_processed_total_force(
    left: CMJForceInput,
    right: CMJForceInput,
    *,
    output_observation_id: InstanceIdentifier | None,
    output_signal_id: InstanceIdentifier | None,
    output_artifact_id: InstanceIdentifier | None,
) -> TotalSupportedForceResult:
    left_signal = left.signal
    right_signal = right.signal
    if left_signal.channel_id is None or right_signal.channel_id is None:
        raise ValueError("bilateral force inputs must identify both channels")
    if left.identity.acquisition.channel is None or right.identity.acquisition.channel is None:
        raise ValueError("bilateral force inputs must identify both acquisition channels")
    left_is_left = left.identity.acquisition.channel.role is ChannelRole.LEFT_FORCE_PLATFORM
    ordered = (left, right) if left_is_left else (right, left)
    first, second = ordered
    digest = _output_digest(
        *ordered,
        operation=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
    )
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"cmj-total-force:{digest}"
    )
    signal_id = output_signal_id or InstanceIdentifier("signal", f"cmj-total-force:{digest}")
    artifact_id = output_artifact_id or InstanceIdentifier("artifact", f"cmj-total-force:{digest}")
    acquisition_id = InstanceIdentifier("acquisition", f"cmj-total-force:{digest}")
    processing_run_id = InstanceIdentifier("processing-run", f"cmj-total-force:{digest}")
    output_channel_id = "total-supported-vertical-force"
    first_samples = first.signal.samples
    second_samples = second.signal.samples
    summed_samples = tuple(
        left_value + right_value
        for left_value, right_value in zip(first_samples, second_samples, strict=True)
    )
    combination_lineage = CombinationLineage(
        kind=CombinationLineageKind.DYNAMISLM_COMBINED_OUTPUT,
        source_channels=(first.signal.channel_id or "", second.signal.channel_id or ""),
        method=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
    )
    output_acquisition = _make_output_acquisition_identity(
        first,
        output_artifact_id=artifact_id,
        output_acquisition_id=acquisition_id,
        output_channel_id=output_channel_id,
        combination_lineage=combination_lineage,
        processing_state=SignalProcessingState.SYSTEM_PROCESSED,
    )
    output_identity_id = ScientificIdentifier(
        "dynamislm",
        "measurement-identity",
        f"cmj-total-supported-vertical-force-{digest}",
        CMJ_REGISTRY_VERSION,
    )
    output_processing = ProcessingIdentity(
        estimator=None,
        registered_operation=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
        method_parameters=(
            MetadataEntry(
                "operation_version", CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM.identifier.version
            ),
            MetadataEntry("left_source_signal_id", first.signal.signal_id.qualified),
            MetadataEntry("right_source_signal_id", second.signal.signal_id.qualified),
            MetadataEntry("output_unit", _unit_id(NEWTON)),
            MetadataEntry("resampling", "none"),
            MetadataEntry("interpolation", "none"),
            MetadataEntry("time_shift", "none"),
            MetadataEntry("sign_flip", "none"),
        ),
        unit=NEWTON,
        sign_convention=_input_sign(first),
    )
    output_identity = CMJMeasurementIdentity(
        identity_id=output_identity_id,
        semantic=_derived_semantic(
            first.identity,
            measurand=CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND,
            metric=CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC,
        ),
        acquisition=output_acquisition,
        processing=output_processing,
        version=VersionIdentity(
            processing_method=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
            method_registry_version=CMJ_REGISTRY_VERSION,
            software_version=RES35_SOFTWARE_VERSION,
        ),
    )
    processed_signal = ProcessedVerticalForceSignal(
        signal_id=signal_id,
        source_artifact_id=artifact_id,
        acquisition_id=acquisition_id,
        acquisition_identity_id=output_identity.identity_id,
        source_signal_ids=(first.signal.signal_id, second.signal.signal_id),
        source_artifact_ids=(first.source_artifact.artifact_id, second.source_artifact.artifact_id),
        processing_run_id=processing_run_id,
        samples=summed_samples,
        timebase=_required_timebase(first),
        channel_id=output_channel_id,
        unit=NEWTON,
        physical_axis=_required_axis(first),
        reference_frame=_required_frame(first),
        sign_convention=_required_sign(first),
    )
    output_artifact = _processed_artifact(processed_signal, acquisition_id)
    output_acquisition_record = AcquisitionRecord(
        acquisition_id=acquisition_id,
        device=CMJ_DYNAMISLM_PROCESSING_SYSTEM,
        source_artifact_id=artifact_id,
        sensor_channel=output_channel_id,
        sampling=output_acquisition.sampling,
        calibration_reference=None,
        hardware_firmware=None,
    )
    processing_run = ProcessingRun(
        processing_run_id=processing_run_id,
        source_artifact_ids=(first.source_artifact.artifact_id, second.source_artifact.artifact_id),
        method=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
        parameters=output_processing.method_parameters,
        software_version=RES35_SOFTWARE_VERSION,
        output_observation_id=observation_id,
    )
    base_provenance = _merge_provenance(
        first.observation.provenance,
        second.observation.provenance,
    )
    provenance = _provenance_with_run(
        base_provenance,
        processing_run=processing_run,
        output_observation_id=observation_id,
        source_observation_ids=_input_observation_ids(first, second),
        source_acquisition_ids=(
            first.acquisition.acquisition_id,
            second.acquisition.acquisition_id,
        ),
        output_artifacts=(output_artifact,),
        output_acquisitions=(output_acquisition_record,),
        produced_artifact_ids=(artifact_id,),
        recorded_at=base_provenance.recorded_at,
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"cmj-total-force:{digest}"),
        value=StructuredOutputReference(
            artifact_id=artifact_id,
            schema=CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_SCHEMA,
        ),
        unit=NEWTON,
        classification=ScientificClassification(
            value_origin=ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
            scientific_roles=(),
        ),
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=first.observation.context,
        identity=output_identity,
        result=result,
        provenance=provenance,
    )
    return TotalSupportedForceResult(
        observation=observation,
        signal=processed_signal,
        source_artifact=output_artifact,
        acquisition=output_acquisition_record,
    )


def _arrangement_refusal(
    source: CMJForceInput,
    *,
    blocked_claim: str,
    reason: RefusalReasonCode,
    missing: str,
    extra_observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    return _refusal(
        blocked_claim,
        (reason,),
        (missing,),
        observation_ids=_input_observation_ids(source) + extra_observation_ids,
        refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
    )


def construct_total_supported_vertical_force(
    source: CMJForceInput,
    counterpart: CMJForceInput | None = None,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    output_signal_id: InstanceIdentifier | None = None,
    output_artifact_id: InstanceIdentifier | None = None,
) -> TotalSupportedForceResult | RefusalResult:
    """Construct or preserve the total supported vertical-force series.

    A single-platform or already-combined acquisition is returned unchanged.
    A separate bilateral acquisition requires a second explicit channel and is
    summed element by element only after all identity and timebase checks pass.
    """

    claim = "construct total supported vertical force"
    source_refusal = _input_common_refusal(source, claim)
    if source_refusal is not None:
        return source_refusal
    source_semantics_refusal = _force_semantics_refusal(source, claim)
    if source_semantics_refusal is not None:
        return source_semantics_refusal
    arrangement = source.identity.acquisition.arrangement
    if arrangement is AcquisitionArrangement.SINGLE_PLATFORM:
        channel = source.identity.acquisition.channel
        if channel is None or channel.role is not ChannelRole.SINGLE_FORCE_PLATFORM:
            return _arrangement_refusal(
                source,
                blocked_claim=claim,
                reason=RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED,
                missing="single-platform total-force channel role",
            )
        if counterpart is not None:
            return _arrangement_refusal(
                source,
                blocked_claim=claim,
                reason=RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                missing="counterpart is not valid for a SINGLE_PLATFORM acquisition",
            )
        return TotalSupportedForceResult(
            observation=source.observation,
            signal=source.signal,
            source_artifact=source.source_artifact,
            acquisition=source.acquisition,
        )
    if arrangement is AcquisitionArrangement.BILATERAL_PRECOMBINED:
        channel = source.identity.acquisition.channel
        lineage = source.identity.acquisition.combination_lineage
        if (
            channel is None
            or channel.role is not ChannelRole.PRECOMBINED_VERTICAL_FORCE
            or lineage is None
        ):
            return _arrangement_refusal(
                source,
                blocked_claim=claim,
                reason=RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED,
                missing="precombined vertical-force channel and combination lineage",
            )
        if counterpart is not None:
            return _arrangement_refusal(
                source,
                blocked_claim=claim,
                reason=RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                missing="counterpart is not valid for a BILATERAL_PRECOMBINED acquisition",
            )
        return TotalSupportedForceResult(
            observation=source.observation,
            signal=source.signal,
            source_artifact=source.source_artifact,
            acquisition=source.acquisition,
        )
    if arrangement is not AcquisitionArrangement.BILATERAL_SEPARATE:
        return _arrangement_refusal(
            source,
            blocked_claim=claim,
            reason=RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED,
            missing="supported total-force acquisition arrangement",
        )
    if counterpart is None:
        return _arrangement_refusal(
            source,
            blocked_claim=claim,
            reason=RefusalReasonCode.BILATERAL_INPUTS_REQUIRED,
            missing="explicit right/left force-platform counterpart",
        )
    counterpart_refusal = _input_common_refusal(counterpart, claim)
    if counterpart_refusal is not None:
        return counterpart_refusal
    counterpart_semantics_refusal = _force_semantics_refusal(counterpart, claim)
    if counterpart_semantics_refusal is not None:
        return counterpart_semantics_refusal
    return _validate_bilateral_pair(
        source,
        counterpart,
        claim=claim,
        output_observation_id=output_observation_id,
        output_signal_id=output_signal_id,
        output_artifact_id=output_artifact_id,
    )


def _validate_bilateral_pair(
    left_or_right: CMJForceInput,
    counterpart: CMJForceInput,
    *,
    claim: str,
    output_observation_id: InstanceIdentifier | None,
    output_signal_id: InstanceIdentifier | None,
    output_artifact_id: InstanceIdentifier | None,
) -> TotalSupportedForceResult | RefusalResult:
    if isinstance(left_or_right.signal, ProcessedVerticalForceSignal) or isinstance(
        counterpart.signal, ProcessedVerticalForceSignal
    ):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,
            ),
            ("raw or device-declared individual left/right channels, not a combined series",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    first_channel = left_or_right.identity.acquisition.channel
    second_channel = counterpart.identity.acquisition.channel
    if first_channel is None or second_channel is None:
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("explicit left and right channel identities",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    roles = {first_channel.role, second_channel.role}
    if roles != {ChannelRole.LEFT_FORCE_PLATFORM, ChannelRole.RIGHT_FORCE_PLATFORM}:
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("one LEFT_FORCE_PLATFORM and one RIGHT_FORCE_PLATFORM input",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if left_or_right.signal.channel_id == counterpart.signal.channel_id:
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("distinct left and right source channel IDs",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        left_or_right.signal.signal_id == counterpart.signal.signal_id
        or left_or_right.source_artifact.artifact_id == counterpart.source_artifact.artifact_id
        or left_or_right.acquisition.acquisition_id == counterpart.acquisition.acquisition_id
        or left_or_right.identity.identity_id == counterpart.identity.identity_id
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("distinct left/right source signal, artifact, acquisition, and identity instances",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if _context_key(left_or_right.observation.context) != _context_key(
        counterpart.observation.context
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("matching athlete/session/test/trial acquisition context",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if _protocol_key(left_or_right.identity) != _protocol_key(counterpart.identity):
        return _refusal(
            claim,
            (RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,),
            ("matching CMJ protocol identity",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    axis_left = _input_axis(left_or_right)
    axis_right = _input_axis(counterpart)
    frame_left = _input_frame(left_or_right)
    frame_right = _input_frame(counterpart)
    sign_left = _input_sign(left_or_right)
    sign_right = _input_sign(counterpart)
    if not _same_reference(axis_left, axis_right) or not _same_reference(frame_left, frame_right):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED,
            ),
            ("matching vertical axis and reference frame",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if sign_left != sign_right:
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED,
            ),
            ("matching explicit upward-positive sign convention",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    left_identity_timebase = left_or_right.identity.acquisition.timebase
    right_identity_timebase = counterpart.identity.acquisition.timebase
    if (
        left_identity_timebase is None
        or right_identity_timebase is None
        or left_identity_timebase != right_identity_timebase
    ):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,
            ),
            ("matching declared acquisition timebase and clock reference",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if (
        left_or_right.identity.acquisition.acquisition_timestamp
        != counterpart.identity.acquisition.acquisition_timestamp
    ):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,
            ),
            ("matching acquisition timestamps for synchronized source channels",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    left_signal = left_or_right.signal
    right_signal = counterpart.signal
    if left_signal.timebase is None or right_signal.timebase is None:
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,
            ),
            ("explicit timebase on both force signals",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if not _timebase_equal(left_signal.timebase, right_signal.timebase):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED,
            ),
            ("identical synchronized timebase",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if len(left_signal.samples) != len(right_signal.samples):
        return _refusal(
            claim,
            (
                RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
                RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,
            ),
            ("identical sample support",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    try:
        return _build_processed_total_force(
            left_or_right,
            counterpart,
            output_observation_id=output_observation_id,
            output_signal_id=output_signal_id,
            output_artifact_id=output_artifact_id,
        )
    except (TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"registered bilateral sum construction: {exc}",),
            observation_ids=_input_observation_ids(left_or_right, counterpart),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def _as_force_input(
    value: CMJForceInput | TotalSupportedForceResult,
) -> CMJForceInput:
    if isinstance(value, CMJForceInput):
        return value
    return value.as_force_input()


def _segment_refusal(
    force_input: CMJForceInput,
    claim: str,
    reason: RefusalReasonCode,
    missing: str,
    *,
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    return _refusal(
        claim,
        (reason,),
        (missing,),
        observation_ids=(force_input.observation.observation_id,),
        refusal_class=refusal_class,
    )


def _segment_duration(signal: ForceSignal, start: int, end: int) -> float:
    timebase = signal.timebase
    if isinstance(timebase, RegularTimebase):
        return (end - start) / timebase.sample_rate_hz
    if isinstance(timebase, ExplicitTimebase):
        return timebase.times_s[end - 1] - timebase.times_s[start]
    raise ValueError("weighing signal must have a registered timebase")


def _weight_processing_parameters(
    segment: WeighingSegment,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("operation_version", CMJ_SYSTEM_WEIGHT_OPERATION.identifier.version),
        MetadataEntry("selection_method", segment.selection_method.stable_id),
        MetadataEntry("selection_interval", segment.interval_semantics),
        MetadataEntry(
            "selection_parameters",
            canonical_json(segment.selection_parameters),
        ),
        MetadataEntry("source_signal_id", segment.source_signal_id.qualified),
        MetadataEntry("source_artifact_id", segment.source_artifact_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", segment.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("start_index", segment.start_index),
        MetadataEntry("end_index", segment.end_index),
        MetadataEntry("estimator", CMJ_SYSTEM_WEIGHT_MEAN_FORCE.stable_id),
        MetadataEntry("estimator_statistic", "arithmetic_mean"),
        MetadataEntry("output_unit", _unit_id(NEWTON)),
        MetadataEntry("filtering", "none"),
        MetadataEntry("trimming", "none"),
    )


def estimate_system_weight(
    force: CMJForceInput | TotalSupportedForceResult,
    segment: WeighingSegment | None = None,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    output_result_id: InstanceIdentifier | None = None,
) -> SystemWeightResult | RefusalResult:
    """Estimate supported-system weight as mean force over an explicit segment."""

    force_input = _as_force_input(force)
    claim = "estimate system weight"
    if segment is None:
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.WEIGHING_SEGMENT_MISSING,
            "explicit registered weighing segment",
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    source_refusal = _input_common_refusal(force_input, claim)
    if source_refusal is not None:
        return source_refusal
    semantics_refusal = _force_semantics_refusal(force_input, claim)
    if semantics_refusal is not None:
        return semantics_refusal
    arrangement = force_input.identity.acquisition.arrangement
    if arrangement is AcquisitionArrangement.BILATERAL_SEPARATE:
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.BILATERAL_INPUTS_REQUIRED,
            "registered total-force construction for BILATERAL_SEPARATE input",
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if arrangement not in {
        AcquisitionArrangement.SINGLE_PLATFORM,
        AcquisitionArrangement.BILATERAL_PRECOMBINED,
    }:
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED,
            "SINGLE_PLATFORM or valid BILATERAL_PRECOMBINED system definition",
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        segment.source_signal_id != force_input.signal.signal_id
        or segment.source_artifact_id != force_input.source_artifact.artifact_id
        or segment.source_measurement_identity_id != force_input.identity.identity_id
    ):
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.WEIGHING_SEGMENT_INVALID,
            "segment source signal, artifact, and measurement identity linkage",
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if segment.end_index > len(force_input.signal.samples):
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.WEIGHING_SEGMENT_INVALID,
            "segment end_index within source sample support",
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    selected = force_input.signal.samples[segment.start_index : segment.end_index]
    if len(selected) < 2:
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.INSUFFICIENT_WEIGHING_SAMPLES,
            "at least two samples in the explicit weighing segment",
        )
    try:
        mean_force = math.fsum(selected) / len(selected)
        standard_deviation = stdev(selected)
        duration = _segment_duration(
            force_input.signal,
            segment.start_index,
            segment.end_index,
        )
        range_force = max(selected) - min(selected)
        qc = WeighingBaselineQC(
            sample_count=len(selected),
            duration_s=duration,
            mean_force_n=mean_force,
            standard_deviation_n=standard_deviation,
            range_n=range_force,
        )
    except (OverflowError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _segment_refusal(
            force_input,
            claim,
            RefusalReasonCode.WEIGHING_SEGMENT_INVALID,
            f"deterministic segment statistics: {exc}",
        )
    digest = canonical_hash(
        {
            "operation": CMJ_SYSTEM_WEIGHT_OPERATION.stable_id,
            "source_observation": force_input.observation.observation_id.qualified,
            "segment": segment,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"cmj-system-weight:{digest}"
    )
    result_id = output_result_id or InstanceIdentifier("result", f"cmj-system-weight:{digest}")
    identity_id = ScientificIdentifier(
        "dynamislm", "measurement-identity", f"cmj-system-weight-{digest}", CMJ_REGISTRY_VERSION
    )
    processing_parameters = _weight_processing_parameters(segment)
    processing = ProcessingIdentity(
        estimator=CMJ_SYSTEM_WEIGHT_MEAN_FORCE,
        registered_operation=CMJ_SYSTEM_WEIGHT_OPERATION,
        method_parameters=processing_parameters,
        unit=NEWTON,
        sign_convention=_input_sign(force_input),
    )
    identity = _derived_identity(
        force_input.identity,
        identity_id=identity_id,
        measurand=CMJ_SYSTEM_WEIGHT_MEASURAND,
        metric=CMJ_SYSTEM_WEIGHT_METRIC,
        processing=processing,
        processing_method=CMJ_SYSTEM_WEIGHT_OPERATION,
    )
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-system-weight:{digest}"),
        source_artifact_ids=(force_input.source_artifact.artifact_id,),
        method=CMJ_SYSTEM_WEIGHT_OPERATION,
        parameters=processing_parameters,
        software_version=RES35_SOFTWARE_VERSION,
        output_observation_id=observation_id,
    )
    provenance = _provenance_with_run(
        force_input.observation.provenance,
        processing_run=processing_run,
        output_observation_id=observation_id,
        source_observation_ids=(force_input.observation.observation_id,),
        source_acquisition_ids=(force_input.acquisition.acquisition_id,),
    )
    result = MeasurementResult(
        result_id=result_id,
        value=ScalarValue(float(mean_force)),
        unit=NEWTON,
        classification=ScientificClassification(
            value_origin=ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
            scientific_roles=(),
        ),
        quality=MeasurementQuality(
            status=QualityStatus.UNKNOWN,
            flags=qc.quality_flags,
            note="Descriptive baseline QC; acceptability was not adjudicated.",
        ),
        uncertainty=UncertaintyMetadata(
            status=UncertaintyStatus.NOT_ASSESSED,
            description="RES-35 does not register a weighing uncertainty model.",
        ),
        status=ResultStatus.VALID,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=force_input.observation.context,
        identity=identity,
        result=result,
        provenance=provenance,
    )
    return SystemWeightResult(observation=observation, segment=segment, qc=qc)


def _weight_observation(
    value: SystemWeightResult | ScientificMeasurementObservation,
) -> ScientificMeasurementObservation:
    if isinstance(value, SystemWeightResult):
        return value.observation
    return value


def _numeric_scalar(observation: ScientificMeasurementObservation) -> float | None:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        return None
    if not isinstance(value.value, int | float) or not math.isfinite(value.value):
        return None
    return float(value.value)


def _weight_input_refusal(
    observation: ScientificMeasurementObservation,
    claim: str,
) -> RefusalResult | None:
    identity = observation.identity
    value = _numeric_scalar(observation)
    if not isinstance(identity, CMJMeasurementIdentity):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ system-weight measurement identity",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if (
        identity.semantic.measurand.stable_id != CMJ_SYSTEM_WEIGHT_MEASURAND.stable_id
        or identity.semantic.metric_definition.stable_id != CMJ_SYSTEM_WEIGHT_METRIC.stable_id
        or identity.processing.registered_operation is None
        or identity.processing.registered_operation.stable_id
        != CMJ_SYSTEM_WEIGHT_OPERATION.stable_id
        or identity.processing.estimator is None
        or identity.processing.estimator.stable_id != CMJ_SYSTEM_WEIGHT_MEAN_FORCE.stable_id
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("registered SYSTEM_WEIGHT operation identity",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if value is None or observation.result.unit is None:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("finite numeric system-weight scalar in N",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if _unit_id(observation.result.unit) != _unit_id(NEWTON):
        return _refusal(
            claim,
            (RefusalReasonCode.FORCE_UNIT_TRANSFORMATION_REQUIRED,),
            ("system-weight value in canonical N",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    classification = observation.result.classification
    if (
        classification.value_origin is not ValueOrigin.DERIVED_MECHANICAL_QUANTITY
        or classification.scientific_roles
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("unambiguous derived-mechanical SYSTEM_WEIGHT classification",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    if observation.result.status is not ResultStatus.VALID:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("valid system-weight result",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if not observation.provenance.processing_runs:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("system-weight processing provenance",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    raw_artifact_id = identity.acquisition.raw_artifact
    if raw_artifact_id is None:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("system-weight source artifact identity",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    matching_runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_observation_id == observation.observation_id
        and run.source_artifact_ids == (raw_artifact_id,)
        and run.method.stable_id == CMJ_SYSTEM_WEIGHT_OPERATION.stable_id
        and run.parameters == identity.processing.method_parameters
        and run.software_version == identity.version.software_version
    )
    if len(matching_runs) != 1:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("exact registered system-weight processing run",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    processing_run = matching_runs[0]
    provenance_edges = observation.provenance.lineage_edges
    source_acquisition_ids = {
        acquisition.acquisition_id
        for acquisition in observation.provenance.acquisitions
        if acquisition.source_artifact_id == raw_artifact_id
    }
    if len(source_acquisition_ids) != 1:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("one unambiguous system-weight source acquisition",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    has_artifact_run_edge = any(
        edge.from_id == raw_artifact_id.qualified
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        for edge in provenance_edges
    )
    has_acquisition_run_edge = any(
        edge.from_id == acquisition_id.qualified
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.PROCESSED_AS
        for acquisition_id in source_acquisition_ids
        for edge in provenance_edges
    )
    has_source_observation_run_edge = any(
        edge.from_id.startswith("observation:")
        and edge.from_id != observation.observation_id.qualified
        and edge.to_id == processing_run.processing_run_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        for edge in provenance_edges
    )
    has_run_output_edge = any(
        edge.from_id == processing_run.processing_run_id.qualified
        and edge.to_id == observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in provenance_edges
    )
    if not (
        source_acquisition_ids
        and has_artifact_run_edge
        and has_acquisition_run_edge
        and has_source_observation_run_edge
        and has_run_output_edge
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("complete system-weight artifact/acquisition/observation provenance path",),
            observation_ids=(observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _mass_processing_parameters(
    gravity: GravityReference,
    weight_identity: CMJMeasurementIdentity,
    *,
    operation: RegistryReference,
    output_measurand: RegistryReference,
    source_weight_observation_id: InstanceIdentifier,
) -> tuple[MetadataEntry, ...]:
    weight_parameters = {
        entry.key: entry.value for entry in weight_identity.processing.method_parameters
    }
    return (
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("operation_version", operation.identifier.version),
        MetadataEntry("output_measurand", output_measurand.stable_id),
        MetadataEntry("source_weight_observation_id", source_weight_observation_id.qualified),
        MetadataEntry(
            "source_weight_operation",
            weight_identity.processing.registered_operation.stable_id
            if weight_identity.processing.registered_operation is not None
            else "unresolved",
        ),
        MetadataEntry(
            "source_weight_estimator",
            weight_identity.processing.estimator.stable_id
            if weight_identity.processing.estimator is not None
            else "unresolved",
        ),
        MetadataEntry(
            "source_weight_selection_method",
            str(weight_parameters.get("selection_method", "unresolved")),
        ),
        MetadataEntry(
            "source_weight_selection_interval",
            str(weight_parameters.get("selection_interval", "unresolved")),
        ),
        MetadataEntry(
            "source_weight_selection_parameters",
            str(weight_parameters.get("selection_parameters", "unresolved")),
        ),
        MetadataEntry(
            "source_weight_start_index",
            weight_parameters.get("start_index", -1),
        ),
        MetadataEntry(
            "source_weight_end_index",
            weight_parameters.get("end_index", -1),
        ),
        MetadataEntry("gravity_value_m_per_s2", gravity.value_m_per_s2),
        MetadataEntry("gravity_unit", _unit_id(gravity.unit)),
        MetadataEntry("gravity_reference_type", gravity.reference_type.value),
        MetadataEntry("gravity_source", gravity.source.stable_id),
        MetadataEntry("gravity_uncertainty_status", gravity.uncertainty.status.value),
        MetadataEntry(
            "gravity_uncertainty_description",
            gravity.uncertainty.description or "not provided",
        ),
    )


def _source_artifact_for_weight(
    observation: ScientificMeasurementObservation,
) -> SourceArtifact | None:
    identity = observation.identity
    if not isinstance(identity, CMJMeasurementIdentity):
        return None
    artifact_id = identity.acquisition.raw_artifact
    if artifact_id is None:
        return None
    matches = tuple(
        artifact
        for artifact in observation.provenance.source_artifacts
        if artifact.artifact_id == artifact_id
    )
    return matches[0] if len(matches) == 1 else None


def _source_acquisition_for_weight(
    observation: ScientificMeasurementObservation,
    artifact_id: InstanceIdentifier,
) -> AcquisitionRecord | None:
    matches = tuple(
        acquisition
        for acquisition in observation.provenance.acquisitions
        if acquisition.source_artifact_id == artifact_id
    )
    return matches[0] if len(matches) == 1 else None


def _derive_mass_observation(
    system_weight: SystemWeightResult | ScientificMeasurementObservation,
    gravity: GravityReference | None = None,
    *,
    operation: RegistryReference,
    measurand: RegistryReference,
    metric: RegistryReference,
    expected_gravity_type: GravityReferenceType,
    claim: str,
    output_prefix: str,
    result_note: str,
    output_observation_id: InstanceIdentifier | None = None,
    output_result_id: InstanceIdentifier | None = None,
) -> tuple[ScientificMeasurementObservation, InstanceIdentifier] | RefusalResult:
    """Build one explicitly identified mass or mass-equivalent observation."""

    weight_observation = _weight_observation(system_weight)
    weight_refusal = _weight_input_refusal(weight_observation, claim)
    if weight_refusal is not None:
        return weight_refusal
    if gravity is None:
        reason_codes: tuple[RefusalReasonCode, ...]
        missing_information: tuple[str, ...]
        safe_descriptions: tuple[str, ...]
        if expected_gravity_type is GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION:
            reason_codes = (
                RefusalReasonCode.GRAVITY_REFERENCE_MISSING,
                RefusalReasonCode.LOCAL_GRAVITY_REQUIRED,
            )
            missing_information = (
                "explicit applicable local gravitational acceleration reference/value",
            )
            safe_descriptions = (
                "the valid SYSTEM_WEIGHT observation remains safely describable in N",
                "no PHYSICAL_SYSTEM_MASS or BODY_MASS value is emitted without local gravity",
            )
        else:
            reason_codes = (RefusalReasonCode.GRAVITY_REFERENCE_MISSING,)
            missing_information = ("explicit registered STANDARD_GRAVITY reference (g_n)",)
            safe_descriptions = (
                "the valid SYSTEM_WEIGHT observation remains safely describable in N",
                "no STANDARD_GRAVITY_MASS_EQUIVALENT or BODY_MASS value is emitted without g_n",
            )
        return _refusal(
            claim,
            reason_codes,
            missing_information,
            observation_ids=(weight_observation.observation_id,),
            safe_descriptions=safe_descriptions,
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    try:
        _finite(gravity.value_m_per_s2, "gravity value")
        if gravity.value_m_per_s2 <= 0:
            raise ValueError("gravity value must be positive")
        if _unit_id(gravity.unit) != _unit_id(METERS_PER_SECOND_SQUARED):
            raise ValueError("gravity unit is not m/s^2")
        if not isinstance(gravity.reference_type, GravityReferenceType):
            raise ValueError("gravity reference type is not registered")
    except (TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_INVALID,),
            (f"valid explicit gravity reference: {exc}",),
            observation_ids=(weight_observation.observation_id,),
            safe_descriptions=(
                "the valid SYSTEM_WEIGHT observation remains safely describable in N",
                f"no {measurand.display_label} or BODY_MASS value is emitted under invalid "
                "gravity metadata",
            ),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if gravity.reference_type is not expected_gravity_type:
        if expected_gravity_type is GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION:
            reason_codes = (
                RefusalReasonCode.LOCAL_GRAVITY_REQUIRED,
                RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH,
            )
            missing_information = (
                "applicable local gravitational acceleration, not STANDARD_GRAVITY",
            )
        else:
            reason_codes = (RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH,)
            missing_information = ("the registered STANDARD_GRAVITY reference (g_n)",)
        return _refusal(
            claim,
            reason_codes,
            missing_information,
            observation_ids=(weight_observation.observation_id,),
            safe_descriptions=(
                "the valid SYSTEM_WEIGHT observation remains safely describable in N",
                f"no {measurand.display_label} value is emitted under the mismatched gravity "
                "semantics",
            ),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    weight_value = _numeric_scalar(weight_observation)
    if weight_value is None:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("finite numeric SYSTEM_WEIGHT scalar",),
            observation_ids=(weight_observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    mass_value = weight_value / gravity.value_m_per_s2
    if not math.isfinite(mass_value):
        return _refusal(
            claim,
            (RefusalReasonCode.GRAVITY_REFERENCE_INVALID,),
            ("finite W/g system-mass result",),
            observation_ids=(weight_observation.observation_id,),
            safe_descriptions=(
                "the valid SYSTEM_WEIGHT observation remains safely describable in N",
                f"no {measurand.display_label} or BODY_MASS value is emitted from a nonfinite "
                "derivation",
            ),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    weight_identity = weight_observation.identity
    if not isinstance(weight_identity, CMJMeasurementIdentity):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("CMJ system-weight identity",),
            observation_ids=(weight_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_artifact = _source_artifact_for_weight(weight_observation)
    if source_artifact is None:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("system-weight source artifact in provenance",),
            observation_ids=(weight_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_acquisition = _source_acquisition_for_weight(
        weight_observation,
        source_artifact.artifact_id,
    )
    if source_acquisition is None:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("system-weight source acquisition in provenance",),
            observation_ids=(weight_observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    digest = canonical_hash(
        {
            "operation": operation.stable_id,
            "source_observation": weight_observation.observation_id.qualified,
            "measurand": measurand.stable_id,
            "gravity": gravity,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"{output_prefix}:{digest}"
    )
    result_id = output_result_id or InstanceIdentifier("result", f"{output_prefix}:{digest}")
    identity_id = ScientificIdentifier(
        "dynamislm", "measurement-identity", f"{output_prefix}-{digest}", CMJ_REGISTRY_VERSION
    )
    processing_parameters = _mass_processing_parameters(
        gravity,
        weight_identity,
        operation=operation,
        output_measurand=measurand,
        source_weight_observation_id=weight_observation.observation_id,
    )
    processing = ProcessingIdentity(
        registered_operation=operation,
        method_parameters=processing_parameters,
        unit=KILOGRAM,
    )
    identity = _derived_identity(
        weight_identity,
        identity_id=identity_id,
        measurand=measurand,
        metric=metric,
        processing=processing,
        processing_method=operation,
        software_version=RES44_SOFTWARE_VERSION,
    )
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"{output_prefix}:{digest}"),
        source_artifact_ids=(source_artifact.artifact_id,),
        method=operation,
        parameters=processing_parameters,
        software_version=RES44_SOFTWARE_VERSION,
        output_observation_id=observation_id,
    )
    evidence_reference = EvidenceReference(
        reference=RES44_DECISION_MASS_METROLOGY,
        applicability_note=(
            "Defines the distinction between physical system mass and the standard-gravity "
            "mass equivalent for this registered operation."
        ),
    )
    provenance = _provenance_with_run(
        weight_observation.provenance,
        processing_run=processing_run,
        output_observation_id=observation_id,
        source_observation_ids=(weight_observation.observation_id,),
        source_acquisition_ids=(source_acquisition.acquisition_id,),
        supported_by=(gravity.source, RES44_DECISION_MASS_METROLOGY),
        evidence_references=(evidence_reference,),
        metrological_traceability=(gravity.source,),
    )
    result = MeasurementResult(
        result_id=result_id,
        value=ScalarValue(float(mass_value)),
        unit=KILOGRAM,
        classification=ScientificClassification(
            value_origin=ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
            scientific_roles=(),
        ),
        quality=MeasurementQuality(
            status=weight_observation.result.quality.status,
            flags=tuple(
                dict.fromkeys(
                    (*weight_observation.result.quality.flags, "GRAVITY_REFERENCE_EXPLICIT")
                )
            ),
            note=result_note,
        ),
        uncertainty=UncertaintyMetadata(
            status=UncertaintyStatus.LIMITED,
            description=(
                "No RES-44 propagation model for force or gravity uncertainty is registered."
            ),
        ),
        status=ResultStatus.VALID,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=weight_observation.context,
        identity=identity,
        result=result,
        provenance=provenance,
    )
    return observation, weight_observation.observation_id


def derive_physical_system_mass(
    system_weight: SystemWeightResult | ScientificMeasurementObservation,
    gravity: GravityReference | None = None,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    output_result_id: InstanceIdentifier | None = None,
) -> PhysicalSystemMassResult | RefusalResult:
    """Derive physical supported-system mass using explicitly applicable local gravity."""

    derived = _derive_mass_observation(
        system_weight,
        gravity,
        operation=CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT,
        measurand=CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND,
        metric=CMJ_PHYSICAL_SYSTEM_MASS_METRIC,
        expected_gravity_type=GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
        claim="derive physical system mass",
        output_prefix="cmj-physical-system-mass",
        result_note=(
            "Physical supported-system mass under the supplied applicable local gravitational "
            "acceleration; body-mass equivalence is not established."
        ),
        output_observation_id=output_observation_id,
        output_result_id=output_result_id,
    )
    if isinstance(derived, RefusalResult):
        return derived
    observation, source_weight_observation_id = derived
    if gravity is None:
        raise AssertionError("validated physical mass derivation requires gravity")
    return PhysicalSystemMassResult(
        observation=observation,
        gravity_reference=gravity,
        source_system_weight_observation_id=source_weight_observation_id,
    )


def derive_standard_gravity_mass_equivalent(
    system_weight: SystemWeightResult | ScientificMeasurementObservation,
    gravity: GravityReference | None = None,
    *,
    output_observation_id: InstanceIdentifier | None = None,
    output_result_id: InstanceIdentifier | None = None,
) -> StandardGravityMassEquivalentResult | RefusalResult:
    """Derive the explicit conventional reference quantity ``W/g_n``."""

    derived = _derive_mass_observation(
        system_weight,
        gravity,
        operation=CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT,
        measurand=CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND,
        metric=CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_METRIC,
        expected_gravity_type=GravityReferenceType.STANDARD_GRAVITY,
        claim="derive standard-gravity mass equivalent",
        output_prefix="cmj-standard-gravity-mass-equivalent",
        result_note=(
            "Reference quantity W/g_n using conventional standard gravity; it is not physical "
            "system mass unless a separate standard-weight identity is established, and body-"
            "mass equivalence is not established."
        ),
        output_observation_id=output_observation_id,
        output_result_id=output_result_id,
    )
    if isinstance(derived, RefusalResult):
        return derived
    observation, source_weight_observation_id = derived
    if gravity is None:
        raise AssertionError("validated standard-gravity equivalent derivation requires gravity")
    return StandardGravityMassEquivalentResult(
        observation=observation,
        gravity_reference=gravity,
        source_system_weight_observation_id=source_weight_observation_id,
    )


def derive_body_mass(
    source: (
        PhysicalSystemMassResult
        | StandardGravityMassEquivalentResult
        | ScientificMeasurementObservation
        | None
    ) = None,
) -> RefusalResult:
    """Refuse BODY_MASS because RES-44 emits only supported-system quantities."""

    observation_ids: tuple[InstanceIdentifier, ...] = ()
    if source is not None:
        observation = source.observation if hasattr(source, "observation") else source
        observation_ids = (observation.observation_id,)
    return _refusal(
        "claim body mass from CMJ force-platform system mass",
        (RefusalReasonCode.BODY_MASS_CLAIM_UNSUPPORTED,),
        (
            "separately authorized unloaded body-mass method and prerequisites",
            "explicit body-mass equivalence decision",
        ),
        observation_ids=observation_ids,
        safe_descriptions=(
            "SYSTEM_WEIGHT and the selected supported-system mass measurand remain separately "
            "describable",
            "no external-load value is silently subtracted and no BODY_MASS value is emitted",
        ),
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


type DerivedMeasurement = (
    SystemWeightResult
    | PhysicalSystemMassResult
    | StandardGravityMassEquivalentResult
    | ScientificMeasurementObservation
)


def _derived_parts(
    value: DerivedMeasurement,
) -> tuple[ScientificMeasurementObservation, WeighingSegment | None]:
    if isinstance(value, SystemWeightResult):
        return value.observation, value.segment
    if isinstance(value, PhysicalSystemMassResult | StandardGravityMassEquivalentResult):
        return value.observation, None
    return value, None


def _derived_missing(identity: MeasurementIdentity, side: str) -> tuple[str, ...]:
    if not isinstance(identity, CMJMeasurementIdentity):
        return (f"{side}.CMJ measurement identity",)
    missing: list[str] = []
    semantic = identity.semantic
    acquisition = identity.acquisition
    processing = identity.processing
    prefix = f"{side}.identity"
    if semantic.protocol is None or semantic.protocol_identity is None:
        missing.append(f"{prefix}.protocol")
    if acquisition.device is None:
        missing.append(f"{prefix}.acquisition.device")
    if acquisition.measuring_system is None:
        missing.append(f"{prefix}.acquisition.measuring_system")
    if acquisition.arrangement is None:
        missing.append(f"{prefix}.acquisition.arrangement")
    if acquisition.physical_axis is None:
        missing.append(f"{prefix}.acquisition.physical_axis")
    if acquisition.reference_frame is None:
        missing.append(f"{prefix}.acquisition.reference_frame")
    if acquisition.unit is None:
        missing.append(f"{prefix}.acquisition.unit")
    if acquisition.sign_convention is None:
        missing.append(f"{prefix}.acquisition.sign_convention")
    if processing.registered_operation is None:
        missing.append(f"{prefix}.processing.registered_operation")
    if processing.unit is None:
        missing.append(f"{prefix}.processing.unit")
    if identity.version.software_version.strip() == "":
        missing.append(f"{prefix}.version.software_version")
    mass_measurands = {
        CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND.stable_id,
        CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND.stable_id,
    }
    mass_operations = {
        CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT.stable_id,
        CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT.stable_id,
    }
    if semantic.measurand.stable_id in mass_measurands or (
        processing.registered_operation is not None
        and processing.registered_operation.stable_id in mass_operations
    ):
        parameter_keys = {entry.key for entry in processing.method_parameters}
        for key in (
            "operation_id",
            "operation_version",
            "output_measurand",
            "source_weight_observation_id",
            "gravity_value_m_per_s2",
            "gravity_unit",
            "gravity_reference_type",
            "gravity_source",
        ):
            if key not in parameter_keys:
                missing.append(f"{prefix}.processing.method_parameters.{key}")
    return tuple(missing)


def _parameter_key(
    parameters: tuple[MetadataEntry, ...],
    *,
    ignored_keys: frozenset[str] = frozenset(),
) -> tuple[tuple[str, object], ...]:
    return tuple((entry.key, entry.value) for entry in parameters if entry.key not in ignored_keys)


def _identity_derived_differences(
    left: MeasurementIdentity,
    right: MeasurementIdentity,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(left, CMJMeasurementIdentity) or not isinstance(
        right, CMJMeasurementIdentity
    ):
        return ((ComparabilityReasonCode.IDENTITY_MISMATCH, "CMJ measurement identity"),)
    differences: list[tuple[str, str]] = []
    if _protocol_key(left) != _protocol_key(right):
        differences.append((ComparabilityReasonCode.PROTOCOL_MISMATCH, "protocol"))
    if not _same_reference(left.semantic.construct, right.semantic.construct):
        differences.append((ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH, "construct"))
    if not _same_reference(left.semantic.measurand, right.semantic.measurand):
        mass_measurands = {
            CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND.stable_id,
            CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND.stable_id,
        }
        if (
            left.semantic.measurand.stable_id in mass_measurands
            and right.semantic.measurand.stable_id in mass_measurands
        ):
            differences.append((ComparabilityReasonCode.MASS_MEASURAND_MISMATCH, "measurand"))
        else:
            differences.append((ComparabilityReasonCode.MEASURAND_MISMATCH, "measurand"))
    if not _same_reference(left.semantic.metric_definition, right.semantic.metric_definition):
        differences.append((ComparabilityReasonCode.IDENTITY_MISMATCH, "metric_definition"))
    left_acquisition = left.acquisition
    right_acquisition = right.acquisition
    if not _same_reference(left_acquisition.device, right_acquisition.device) or not (
        _same_reference(left_acquisition.measuring_system, right_acquisition.measuring_system)
    ):
        differences.append((ComparabilityReasonCode.DEVICE_MISMATCH, "device_or_measuring_system"))
    if left_acquisition.arrangement != right_acquisition.arrangement:
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "arrangement"))
    if not _same_reference(left_acquisition.physical_axis, right_acquisition.physical_axis):
        differences.append((ComparabilityReasonCode.AXIS_MISMATCH, "physical_axis"))
    if not _same_reference(left_acquisition.reference_frame, right_acquisition.reference_frame):
        differences.append((ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH, "reference_frame"))
    if not _same_reference(left_acquisition.unit, right_acquisition.unit):
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "unit"))
    if left_acquisition.sign_convention != right_acquisition.sign_convention:
        differences.append((ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH, "sign_convention"))
    if left_acquisition.processing_state != right_acquisition.processing_state:
        differences.append((ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "processing_state"))
    if (
        left_acquisition.acquisition_software_version
        != right_acquisition.acquisition_software_version
    ):
        differences.append(
            (ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH, "acquisition_software_version")
        )
    if left_acquisition.sampling != right_acquisition.sampling or (
        left_acquisition.timebase != right_acquisition.timebase
    ):
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "timebase"))
    if left_acquisition.combination_lineage != right_acquisition.combination_lineage:
        differences.append(
            (ComparabilityReasonCode.TOTAL_FORCE_CONSTRUCTION_MISMATCH, "combination_lineage")
        )
    left_processing = left.processing
    right_processing = right.processing
    if not _same_reference(
        left_processing.registered_operation, right_processing.registered_operation
    ):
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "registered_operation"))
    if not _same_reference(left_processing.estimator, right_processing.estimator):
        differences.append((ComparabilityReasonCode.ESTIMATOR_MISMATCH, "estimator"))
    ignored_parameter_keys = frozenset(
        {
            "source_signal_id",
            "source_artifact_id",
            "source_measurement_identity_id",
            "left_source_signal_id",
            "right_source_signal_id",
            "source_weight_observation_id",
        }
    )
    if _parameter_key(left_processing.method_parameters, ignored_keys=ignored_parameter_keys) != (
        _parameter_key(right_processing.method_parameters, ignored_keys=ignored_parameter_keys)
    ):
        if any(
            entry.key.startswith("gravity_")
            for entry in (*left_processing.method_parameters, *right_processing.method_parameters)
        ):
            differences.append((ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH, "gravity"))
        elif left_processing.registered_operation == CMJ_SYSTEM_WEIGHT_OPERATION:
            differences.append(
                (ComparabilityReasonCode.WEIGHING_SEGMENT_MISMATCH, "weighing_segment")
            )
        else:
            differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "method_parameters"))
    if not _same_reference(left_processing.unit, right_processing.unit):
        differences.append(
            (ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "processing_unit")
        )
    if left.version != right.version:
        differences.append((ComparabilityReasonCode.METHOD_MISMATCH, "processing_version"))
    return tuple(differences)


def _comparability_result(
    request: CMJDerivedComparabilityRequest,
    *,
    state: ComparabilityState,
    reason_codes: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    transformations_required: tuple[TransformationRequest, ...] = (),
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
        transformations_required=transformations_required,
        missing_information=missing_information,
        rule_reference=CMJ_DERIVED_COMPARABILITY_RULE,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _is_body_mass_claim(claim: str) -> bool:
    normalized = " ".join(claim.casefold().replace("_", " ").replace("-", " ").split())
    return "body mass" in normalized


def assess_cmj_derived_comparability(
    request: CMJDerivedComparabilityRequest,
) -> ComparabilityResult:
    """Apply the RES-44 claim-relative comparability rule."""

    if _is_body_mass_claim(request.claim):
        return _comparability_result(
            request,
            state=ComparabilityState.NOT_COMPARABLE,
            reason_codes=(ComparabilityReasonCode.BODY_MASS_CLAIM_UNSUPPORTED,),
            conditions=("RES-35 does not register BODY_MASS as an output or comparability claim",),
        )
    missing = _derived_missing(request.left_identity, "left") + _derived_missing(
        request.right_identity, "right"
    )
    if missing:
        return ComparabilityResult(
            result_id=InstanceIdentifier(
                "comparability-result", f"{request.request_id.value}:insufficient-information"
            ),
            request_id=request.request_id,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reason_codes=(ComparabilityReasonCode.MISSING_METADATA,),
            conditions=(),
            transformations_required=request.requested_transformations,
            missing_information=tuple(dict.fromkeys(missing)),
            rule_reference=None,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.UNRESOLVED,
        )
    differences = list(_identity_derived_differences(request.left_identity, request.right_identity))
    if request.left_segment is not None and request.right_segment is not None:
        left_segment_key = (
            request.left_segment.selection_method.stable_id,
            request.left_segment.start_index,
            request.left_segment.end_index,
        )
        right_segment_key = (
            request.right_segment.selection_method.stable_id,
            request.right_segment.start_index,
            request.right_segment.end_index,
        )
        if left_segment_key != right_segment_key:
            differences.append((ComparabilityReasonCode.WEIGHING_SEGMENT_MISMATCH, "segment"))
    if any(reason == ComparabilityReasonCode.MASS_MEASURAND_MISMATCH for reason, _ in differences):
        semantic_reasons = tuple(
            dict.fromkeys(
                reason
                for reason, _ in differences
                if reason
                in (
                    ComparabilityReasonCode.MASS_MEASURAND_MISMATCH,
                    ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH,
                )
            )
        )
        return _comparability_result(
            request,
            state=ComparabilityState.NOT_COMPARABLE,
            reason_codes=semantic_reasons or (ComparabilityReasonCode.MASS_MEASURAND_MISMATCH,),
            conditions=(
                "PHYSICAL_SYSTEM_MASS and STANDARD_GRAVITY_MASS_EQUIVALENT are distinct "
                "measurands and are not interchangeable solely because both are reported in kg",
            ),
            transformations_required=request.requested_transformations,
        )
    if request.requested_transformations and not differences:
        return _comparability_result(
            request,
            state=ComparabilityState.REQUIRES_TRANSFORMATION,
            reason_codes=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            transformations_required=request.requested_transformations,
            conditions=("the requested registered transformation must be applied first",),
        )
    if differences:
        reason_codes = tuple(
            dict.fromkeys(
                (
                    ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,
                    *(reason for reason, _ in differences),
                )
            )
        )
        return _comparability_result(
            request,
            state=ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            reason_codes=reason_codes,
            conditions=(
                "a registered deterministic RES-35 method/system/gravity bridge is required",
            ),
            transformations_required=request.requested_transformations,
        )
    return _comparability_result(request, state=ComparabilityState.COMPARABLE)


def compare_cmj_derived_measurements(
    left: DerivedMeasurement,
    right: DerivedMeasurement,
    *,
    claim: str,
    request_id: InstanceIdentifier,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Compare derived observations without flattening their scientific identity."""

    left_observation, left_segment = _derived_parts(left)
    right_observation, right_segment = _derived_parts(right)
    return assess_cmj_derived_comparability(
        CMJDerivedComparabilityRequest(
            request_id=request_id,
            left_observation_id=left_observation.observation_id,
            right_observation_id=right_observation.observation_id,
            left_identity=left_observation.identity,
            right_identity=right_observation.identity,
            claim=claim,
            left_segment=left_segment,
            right_segment=right_segment,
            requested_transformations=requested_transformations,
        )
    )


def refusal_for_cmj_derived_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Refuse only an unresolved RES-44 comparison and retain both observations."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    mapping: dict[ComparabilityReasonCode, tuple[RefusalReasonCode, ...]] = {
        ComparabilityReasonCode.WEIGHING_SEGMENT_MISMATCH: (
            RefusalReasonCode.WEIGHING_SEGMENT_INVALID,
        ),
        ComparabilityReasonCode.ESTIMATOR_MISMATCH: (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        ComparabilityReasonCode.TOTAL_FORCE_CONSTRUCTION_MISMATCH: (
            RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE,
        ),
        ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH: (
            RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH,
        ),
        ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH: (
            RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED,
        ),
        ComparabilityReasonCode.BODY_MASS_CLAIM_UNSUPPORTED: (
            RefusalReasonCode.BODY_MASS_CLAIM_UNSUPPORTED,
        ),
        ComparabilityReasonCode.MEASURAND_MISMATCH: (RefusalReasonCode.MEASURAND_MISMATCH,),
        ComparabilityReasonCode.MASS_MEASURAND_MISMATCH: (
            RefusalReasonCode.MASS_MEASURAND_MISMATCH,
        ),
        ComparabilityReasonCode.AXIS_MISMATCH: (RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,),
        ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH: (
            RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,
        ),
        ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH: (
            RefusalReasonCode.SIGN_CONVENTION_MISMATCH,
        ),
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,
        ),
        ComparabilityReasonCode.PROCESSING_STATE_MISMATCH: (
            RefusalReasonCode.PROCESSING_STATE_UNKNOWN,
        ),
        ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH: (
            RefusalReasonCode.SOFTWARE_PIPELINE_NOT_ESTABLISHED,
        ),
        ComparabilityReasonCode.METHOD_MISMATCH: (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        ComparabilityReasonCode.MISSING_METADATA: (RefusalReasonCode.MISSING_METADATA,),
        ComparabilityReasonCode.PROTOCOL_MISMATCH: (RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH,),
        ComparabilityReasonCode.DEVICE_MISMATCH: (RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED,),
        ComparabilityReasonCode.ARRANGEMENT_MISMATCH: (
            RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,
        ),
        ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH,
        ),
        ComparabilityReasonCode.BRIDGE_NOT_REGISTERED: (
            RefusalReasonCode.COMPARABILITY_NOT_REGISTERED,
        ),
    }
    mapped_codes: list[RefusalReasonCode] = []
    for code in result.reason_codes:
        mapped: tuple[RefusalReasonCode, ...]
        try:
            normalized_code = ComparabilityReasonCode(code)
        except ValueError:
            mapped = (RefusalReasonCode.COMPARABILITY_NOT_REGISTERED,)
        else:
            mapped = mapping.get(
                normalized_code,
                (RefusalReasonCode.COMPARABILITY_NOT_REGISTERED,),
            )
        for reason in mapped:
            if reason not in mapped_codes:
                mapped_codes.append(reason)
    reason_codes = tuple(mapped_codes)
    if not reason_codes:
        reason_codes = (RefusalReasonCode.COMPARABILITY_NOT_REGISTERED,)
    if result.missing_information:
        missing = result.missing_information
    elif ComparabilityReasonCode.MASS_MEASURAND_MISMATCH in result.reason_codes:
        missing = ("a separately authorized mass-measurand conversion or comparison contract",)
    else:
        missing = ("registered deterministic RES-44 comparability bridge",)
    body_mass_claim = ComparabilityReasonCode.BODY_MASS_CLAIM_UNSUPPORTED in result.reason_codes
    return _refusal(
        blocked_claim,
        reason_codes,
        missing,
        observation_ids=observation_ids,
        safe_descriptions=(
            "each derived observation remains independently describable under its own identity",
            (
                "no BODY_MASS value or BODY_MASS comparability claim is emitted"
                if body_mass_claim
                else "the comparison is blocked until the stated method, system, gravity, or "
                "bridge issue is resolved"
            ),
        ),
        refusal_class=(
            RefusalClass.COMPUTATION_NOT_REGISTERED
            if body_mass_claim
            else RefusalClass.COMPARABILITY_UNESTABLISHED
        ),
    )


__all__ = [
    "RES35_SOFTWARE_VERSION",
    "RES44_SOFTWARE_VERSION",
    "STANDARD_GRAVITY",
    "STANDARD_GRAVITY_VALUE_M_PER_S2",
    "CMJDerivedComparabilityRequest",
    "CMJForceInput",
    "DerivedMeasurement",
    "ForceSignal",
    "GravityReference",
    "GravityReferenceType",
    "PhysicalSystemMassResult",
    "ProcessedVerticalForceSignal",
    "StandardGravityMassEquivalentResult",
    "SystemWeightResult",
    "TotalSupportedForceResult",
    "WeighingBaselineQC",
    "WeighingSegment",
    "assess_cmj_derived_comparability",
    "compare_cmj_derived_measurements",
    "construct_total_supported_vertical_force",
    "derive_body_mass",
    "derive_physical_system_mass",
    "derive_standard_gravity_mass_equivalent",
    "estimate_system_weight",
    "refusal_for_cmj_derived_comparability",
]
