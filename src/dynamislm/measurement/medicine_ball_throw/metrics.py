"""Deterministic MBT distance/release-velocity operations and refusals."""

from __future__ import annotations

import math
from dataclasses import dataclass

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    _require_instance,
    _require_tuple_items,
)
from dynamislm.measurement.medicine_ball_throw.identity import (
    MBTBodyPosture,
    MBTCoordinateEvidence,
    MBTMeasurementIdentity,
    MBTProcessingState,
    MBTReleaseSemantics,
    MBTSensorModality,
    MBTThrowVariant,
    MedicineBallThrowAcquisitionIdentity,
    MedicineBallThrowMeasurementIdentity,
    MedicineBallThrowProcessingIdentity,
    MedicineBallThrowSemanticIdentity,
)
from dynamislm.measurement.medicine_ball_throw.qualification import (
    MBTReleaseVelocityEvidence,
    MBTSourceQualificationEvidence,
    require_qualified_mbt,
)
from dynamislm.measurement.medicine_ball_throw.registry import (
    MBT_DISTANCE_FROM_REGISTERED_COORDINATES_OPERATION,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_OPERATION,
    MBT_REGISTRY_VERSION,
    MBT_SOFTWARE_VERSION,
    MBT_THROW_DISTANCE_MEASURAND,
    MBT_THROW_DISTANCE_METRIC,
    MEDICINE_BALL_THROW_TEST_FAMILY,
    METER,
    METERS_PER_SECOND,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
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
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, register_serializable_type


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MedicineBallThrowMetricResult:
    observation: ScientificMeasurementObservation
    metric: RegistryReference
    source_observations: tuple[ScientificMeasurementObservation, ...]
    coordinate_evidence: MBTCoordinateEvidence | None = None
    release_evidence: MBTReleaseVelocityEvidence | None = None

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.metric, RegistryReference, "metric")
        _require_tuple_items(
            self.source_observations, ScientificMeasurementObservation, "source_observations"
        )
        if not isinstance(self.observation.identity, MBTMeasurementIdentity):
            raise ValueError("MBT result requires MedicineBallThrowMeasurementIdentity")
        if self.observation.identity.semantic.metric_definition != self.metric:
            raise ValueError("MBT metric does not match output identity")
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("MBT result must contain a numeric scalar")
        _finite(value.value, "MBT result")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("MBT result must be valid")
        runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(runs) != 1:
            raise ValueError("MBT result must preserve one output processing run")
        run_id = runs[0].processing_run_id.qualified
        for source in self.source_observations:
            if not any(
                edge.from_id == source.observation_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("MBT result is missing source observation lineage")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        assert isinstance(value, ScalarValue)
        return float(value.value)

    @property
    def unit(self) -> UnitReference | None:
        return self.observation.result.unit

    @property
    def value_m(self) -> float:
        if self.unit != METER:
            raise ValueError("MBT result is not expressed in metres")
        return self.value

    @property
    def value_m_per_s(self) -> float:
        if self.unit != METERS_PER_SECOND:
            raise ValueError("MBT result is not expressed in m/s")
        return self.value


def _refusal(
    claim: str,
    reasons: tuple[RefusalReasonCode | str, ...],
    missing: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.IDENTITY_UNRESOLVED,
    safe: tuple[str, ...] = (),
) -> RefusalResult:
    codes = tuple(item.value if isinstance(item, RefusalReasonCode) else item for item in reasons)
    digest = canonical_hash(
        {"claim": claim, "reasons": codes, "missing": missing, "observation_ids": observation_ids}
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"medicine-ball-throw:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing,
        what_can_still_be_safely_described=safe or ("the exact MBT source observation",),
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        observation_ids=observation_ids,
    )


def _validate_distance_source(
    source_observation: ScientificMeasurementObservation,
    coordinate: MBTCoordinateEvidence,
) -> MedicineBallThrowMeasurementIdentity:
    if not isinstance(source_observation, ScientificMeasurementObservation):
        raise ValueError("MBT source observation is required")
    identity = source_observation.identity
    if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
        raise ValueError("MBT source observation requires MBT identity")
    protocol = identity.semantic.protocol_identity
    if protocol is None:
        raise ValueError("MBT protocol identity is required")
    if coordinate.source_observation_id != source_observation.observation_id:
        raise ValueError("MBT coordinate evidence is bound to another observation")
    if coordinate.source_artifact_id not in {
        item.artifact_id for item in source_observation.provenance.source_artifacts
    } or coordinate.acquisition_id not in {
        item.acquisition_id for item in source_observation.provenance.acquisitions
    }:
        raise ValueError("MBT coordinate evidence is not bound to source provenance")
    if (
        protocol.distance_origin_convention is None
        or protocol.distance_endpoint_convention is None
        or protocol.first_contact_no_roll_convention is None
    ):
        raise ValueError("MBT distance conventions are unresolved")
    if (
        protocol.distance_origin_convention != coordinate.origin_convention
        or protocol.distance_endpoint_convention != coordinate.endpoint_convention
        or protocol.first_contact_no_roll_convention != coordinate.first_contact_no_roll_convention
    ):
        raise ValueError("MBT coordinate convention mismatch")
    if not coordinate.first_contact_observed or not coordinate.no_roll_observed:
        raise ValueError("MBT distance requires first-contact and no-roll evidence")
    if (
        protocol.throw_type is MBTThrowVariant.UNKNOWN
        or protocol.body_posture is MBTBodyPosture.UNKNOWN
    ):
        raise ValueError("MBT throw type/posture is unresolved")
    if protocol.ball_mass_kg is None:
        raise ValueError("MBT ball mass is required")
    return identity


def _output_identity(
    source_identity: MedicineBallThrowMeasurementIdentity,
    *,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    unit: UnitReference,
    parameters: tuple[MetadataEntry, ...],
) -> MedicineBallThrowMeasurementIdentity:
    source_acquisition = source_identity.acquisition
    return MedicineBallThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"mbt-{operation.identifier.key}-{canonical_hash(parameters).removeprefix('sha256:')[:24]}",
            MBT_REGISTRY_VERSION,
        ),
        semantic=MedicineBallThrowSemanticIdentity(
            construct=source_identity.semantic.construct,
            test_family=MEDICINE_BALL_THROW_TEST_FAMILY,
            protocol=source_identity.semantic.protocol,
            measurand=measurand,
            metric_definition=metric,
            protocol_identity=source_identity.semantic.protocol_identity,
        ),
        acquisition=MedicineBallThrowAcquisitionIdentity(
            device=source_acquisition.device,
            raw_artifact=source_acquisition.raw_artifact,
            sensor_channel=source_acquisition.sensor_channel,
            sampling=source_acquisition.sampling,
            calibration_reference=source_acquisition.calibration_reference,
            hardware_firmware=source_acquisition.hardware_firmware,
            provider=source_acquisition.provider,
            sensor_modality=source_acquisition.sensor_modality,
            timebase=source_acquisition.timebase,
            axis_or_frame=source_acquisition.axis_or_frame,
            acquisition_instance_id=source_acquisition.acquisition_instance_id,
            source_series_digest=source_acquisition.source_series_digest,
        ),
        processing=MedicineBallThrowProcessingIdentity(
            registered_operation=operation,
            estimator=operation,
            method_parameters=parameters,
            unit=unit,
            sign_convention=source_identity.processing.sign_convention,
            normalization=source_identity.processing.normalization,
            trial_selection=source_identity.processing.trial_selection,
            aggregation=source_identity.processing.aggregation,
            filtering=source_identity.processing.filtering,
            differentiation_method=source_identity.processing.differentiation_method,
            integration_method=source_identity.processing.integration_method,
            timebase=source_acquisition.timebase,
            processing_state=MBTProcessingState.DYNAMISLM_PROCESSED,
        ),
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=MBT_REGISTRY_VERSION,
            software_version=MBT_SOFTWARE_VERSION,
            hardware_firmware=source_acquisition.hardware_firmware,
        ),
    )


def _build_derived(
    *,
    source_observation: ScientificMeasurementObservation,
    value: float,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    unit: UnitReference,
    parameters: tuple[MetadataEntry, ...],
    coordinate_evidence: MBTCoordinateEvidence | None = None,
    release_evidence: MBTReleaseVelocityEvidence | None = None,
) -> MedicineBallThrowMetricResult:
    if not isinstance(source_observation.identity, MedicineBallThrowMeasurementIdentity):
        raise ValueError("MBT source identity is required")
    _require_instance(source_observation.context, ObservationContext, "context")
    numeric = _finite(value, "MBT derived value")
    identity = _output_identity(
        source_observation.identity,
        metric=metric,
        measurand=measurand,
        operation=operation,
        unit=unit,
        parameters=parameters,
    )
    digest = canonical_hash(
        {
            "operation": operation,
            "metric": metric,
            "value": numeric,
            "parameters": parameters,
            "source_observation_id": source_observation.observation_id,
        }
    ).removeprefix("sha256:")[:24]
    output_id = InstanceIdentifier("observation", f"mbt:{operation.identifier.key}:{digest}")
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"mbt-result:{digest}"),
        content_digest=canonical_hash({"identity": identity, "value": numeric, "metric": metric}),
        media_type="application/vnd.dynamislm.medicine-ball-throw.scalar-metric",
        immutable=True,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"mbt:{operation.identifier.key}:{digest}"
        ),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in source_observation.provenance.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=operation,
        parameters=parameters,
        software_version=MBT_SOFTWARE_VERSION,
        output_entity_id=output_id,
    )
    if not run.source_artifact_ids:
        raise ValueError("MBT derived result requires source artifacts")
    edges = list(source_observation.provenance.lineage_edges)
    for source_id in (
        source_observation.observation_id,
        *(run.source_artifact_ids),
    ):
        edge = LineageEdge(
            source_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    for acquisition in source_observation.provenance.acquisitions:
        edge = LineageEdge(
            acquisition.acquisition_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    for edge in (
        LineageEdge(
            RES68_DECISION_EXPLOSIVE_TEST_FAMILY.stable_id,
            run.processing_run_id.qualified,
            LineageRelation.SUPPORTED_BY,
        ),
        LineageEdge(
            run.processing_run_id.qualified,
            output_artifact.artifact_id.qualified,
            LineageRelation.PRODUCED,
        ),
        LineageEdge(run.processing_run_id.qualified, output_id.qualified, LineageRelation.PRODUCED),
    ):
        if edge not in edges:
            edges.append(edge)
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", output_id.value),
        source_artifacts=tuple(
            sorted(
                (*source_observation.provenance.source_artifacts, output_artifact),
                key=lambda item: item.artifact_id.qualified,
            )
        ),
        acquisitions=source_observation.provenance.acquisitions,
        processing_runs=(*source_observation.provenance.processing_runs, run),
        lineage_edges=tuple(
            sorted(edges, key=lambda item: (item.from_id, item.to_id, item.relation.value))
        ),
        evidence_references=tuple(
            dict.fromkeys(
                (
                    *source_observation.provenance.evidence_references,
                    EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),
                )
            )
        ),
        metrological_traceability=source_observation.provenance.metrological_traceability,
        recorded_at=source_observation.provenance.recorded_at
        or source_observation.context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=output_id,
        context=source_observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"mbt:{operation.identifier.key}:{digest}"),
            value=ScalarValue(numeric),
            unit=unit,
            classification=ScientificClassification(
                ValueOrigin.DYNAMISLM_DERIVED, (ScientificRole.PERFORMANCE_OUTCOME,)
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description="RES-68 deterministic MBT arithmetic; uncertainty is not assessed.",
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return MedicineBallThrowMetricResult(
        observation=observation,
        metric=metric,
        source_observations=(source_observation,),
        coordinate_evidence=coordinate_evidence,
        release_evidence=release_evidence,
    )


def calculate_mbt_throw_distance(
    coordinate_evidence: MBTCoordinateEvidence,
    source_observation: ScientificMeasurementObservation,
    qualification: MBTSourceQualificationEvidence | None = None,
) -> MedicineBallThrowMetricResult | RefusalResult:
    """Calculate exact MBT distance from registered origin and endpoint coordinates."""

    claim = "calculate medicine-ball throw distance"
    try:
        _validate_distance_source(source_observation, coordinate_evidence)
        if qualification is not None:
            require_qualified_mbt(qualification, source_observation)
        value = coordinate_evidence.endpoint_coordinate_m - coordinate_evidence.origin_coordinate_m
        if value < 0 or not math.isfinite(value):
            raise ValueError("MBT distance must be finite and non-negative")
        parameters = (
            MetadataEntry("origin_coordinate_m", coordinate_evidence.origin_coordinate_m),
            MetadataEntry("endpoint_coordinate_m", coordinate_evidence.endpoint_coordinate_m),
            MetadataEntry("origin_convention", coordinate_evidence.origin_convention.stable_id),
            MetadataEntry("endpoint_convention", coordinate_evidence.endpoint_convention.stable_id),
            MetadataEntry("coordinate_frame", coordinate_evidence.coordinate_frame.stable_id),
            MetadataEntry("first_contact_observed", coordinate_evidence.first_contact_observed),
            MetadataEntry("no_roll_observed", coordinate_evidence.no_roll_observed),
        )
        return _build_derived(
            source_observation=source_observation,
            value=value,
            metric=MBT_THROW_DISTANCE_METRIC,
            measurand=MBT_THROW_DISTANCE_MEASURAND,
            operation=MBT_DISTANCE_FROM_REGISTERED_COORDINATES_OPERATION,
            unit=METER,
            parameters=parameters,
            coordinate_evidence=coordinate_evidence,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.MISSING_METADATA,),
            ("exact MBT protocol, origin, endpoint and first-contact/no-roll evidence",),
            (source_observation.observation_id,)
            if isinstance(source_observation, ScientificMeasurementObservation)
            else (),
        )


def calculate_mbt_instrumented_release_velocity(
    evidence: MBTReleaseVelocityEvidence,
    qualification: MBTSourceQualificationEvidence | None = None,
) -> MedicineBallThrowMetricResult | RefusalResult:
    """Select the exact qualified velocity sample at the registered release event."""

    claim = "calculate instrumented medicine-ball release velocity"
    try:
        _require_instance(evidence, MBTReleaseVelocityEvidence, "evidence")
        source = evidence.observation
        identity = source.identity
        if not isinstance(identity, MedicineBallThrowMeasurementIdentity):
            raise ValueError("MBT release source requires MBT identity")
        protocol = identity.semantic.protocol_identity
        if protocol is None or protocol.release_semantics is MBTReleaseSemantics.UNKNOWN:
            raise ValueError("MBT release semantics are unresolved")
        if (
            identity.acquisition.device is None
            or identity.acquisition.sensor_modality is MBTSensorModality.UNKNOWN
        ):
            raise ValueError("MBT instrumented device/modality identity is required")
        if qualification is not None:
            require_qualified_mbt(qualification, source)
        value = evidence.release_velocity_m_per_s
        parameters = (
            MetadataEntry("release_event_id", evidence.release_event.event_id.qualified),
            MetadataEntry("release_sample_index", evidence.release_event.sample_index),
            MetadataEntry("release_event_time_s", evidence.release_event.event_time_s),
            MetadataEntry("velocity_definition", evidence.velocity_definition.stable_id),
            MetadataEntry("coordinate_frame", evidence.coordinate_frame.stable_id),
            MetadataEntry("source_series_digest", evidence.source_series_digest),
        )
        return _build_derived(
            source_observation=source,
            value=value,
            metric=MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC,
            measurand=MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND,
            operation=MBT_INSTRUMENTED_RELEASE_VELOCITY_OPERATION,
            unit=METERS_PER_SECOND,
            parameters=parameters,
            release_evidence=evidence,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("qualified trajectory, exact release event, frame, timebase and velocity definition",),
            (evidence.observation.observation_id,)
            if isinstance(evidence, MBTReleaseVelocityEvidence)
            else (),
        )


def _unregistered(claim: str, evidence: object | None = None) -> RefusalResult:
    observation_ids = (
        (evidence.observation.observation_id,)
        if isinstance(evidence, MBTReleaseVelocityEvidence | MedicineBallThrowMetricResult)
        else ()
    )
    return _refusal(
        claim,
        (RefusalReasonCode.NO_REGISTERED_OPERATION, "COMPUTATION_NOT_REGISTERED"),
        ("a separately registered MBT mechanical-power or normative method",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe=("the exact MBT distance or release-velocity observation",),
    )


def calculate_mbt_distance_as_power(evidence: object | None = None) -> RefusalResult:
    return _unregistered("calculate MBT power from throw distance", evidence)


def calculate_mbt_generic_upper_body_power(evidence: object | None = None) -> RefusalResult:
    return _unregistered("calculate generic upper-body power from MBT distance", evidence)


def calculate_mbt_release_velocity_from_distance(evidence: object | None = None) -> RefusalResult:
    return _refusal(
        "infer MBT release velocity from throw distance",
        (RefusalReasonCode.NO_REGISTERED_OPERATION, "DISTANCE_IS_NOT_RELEASE_VELOCITY"),
        ("qualified instrumented trajectory and explicit release event",),
        (),
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe=("the exact MBT distance observation",),
    )


def calculate_mbt_protocol_independent_normative_score(
    evidence: object | None = None,
) -> RefusalResult:
    return _unregistered("calculate protocol-independent MBT normative score", evidence)


def compare_mbt_protocols_as_equivalent(evidence: object | None = None) -> RefusalResult:
    return _unregistered("claim MBT cross-protocol equivalence", evidence)


calculate_medicine_ball_throw_distance = calculate_mbt_throw_distance
calculate_medicine_ball_release_velocity = calculate_mbt_instrumented_release_velocity


__all__ = [
    "MedicineBallThrowMetricResult",
    "calculate_mbt_distance_as_power",
    "calculate_mbt_generic_upper_body_power",
    "calculate_mbt_instrumented_release_velocity",
    "calculate_mbt_protocol_independent_normative_score",
    "calculate_mbt_release_velocity_from_distance",
    "calculate_mbt_throw_distance",
    "calculate_medicine_ball_release_velocity",
    "calculate_medicine_ball_throw_distance",
    "compare_mbt_protocols_as_equivalent",
]
