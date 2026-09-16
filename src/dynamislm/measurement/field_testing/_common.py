"""Shared source, provenance, context, result, and refusal helpers for RES-67."""

from __future__ import annotations

import datetime as datetime_module
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from dynamislm.measurement.field_testing.identity import (
    FieldTestArtifactStatus,
    FieldTestingAcquisitionRecord,
    FieldTestingMeasurementIdentity,
    FieldTestingProcessingIdentity,
    FieldTestingProtocolIdentity,
    FieldTestingSemanticIdentity,
    FieldTestingSourceArtifact,
    FieldTestProcessingComponentStatus,
    FieldTestProcessingState,
    FieldTestQualificationStatus,
)
from dynamislm.measurement.field_testing.registry import (
    FIELD_TEST_QUALIFICATION_MEASURAND,
    FIELD_TEST_QUALIFICATION_METRIC,
    FIELD_TEST_SOURCE_QUALIFICATION_OPERATION,
    FIELD_TESTING_REGISTRY_VERSION,
    FIELD_TESTING_SOFTWARE_VERSION,
    RES67_DECISION_FIELD_TESTING,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    _require_instance,
    _require_tuple_items,
)
from dynamislm.measurement.observation import (
    ObservationContext,
    ScientificMeasurementObservation,
    create_derived_observation,
)
from dynamislm.measurement.result import (
    CategoricalValue,
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import (
    ScientificClassification,
    ScientificRole,
    ValueOrigin,
)
from dynamislm.provenance.models import (
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


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _protocol_processing_components(
    protocol: FieldTestingProtocolIdentity,
) -> tuple[
    tuple[RegistryReference, ...],
    FieldTestProcessingComponentStatus,
    RegistryReference | None,
    RegistryReference | None,
]:
    if protocol.filtering is None:
        filtering: tuple[RegistryReference, ...] = ()
        filtering_status = FieldTestProcessingComponentStatus.UNKNOWN
    elif protocol.filtering:
        filtering = protocol.filtering
        filtering_status = FieldTestProcessingComponentStatus.REGISTERED
    else:
        filtering = ()
        filtering_status = FieldTestProcessingComponentStatus.NONE_DECLARED
    return filtering, filtering_status, protocol.smoothing, protocol.interpolation


def _numeric_scalar(observation: ScientificMeasurementObservation) -> float:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        raise ValueError("field-test result must contain a numeric scalar")
    if not isinstance(value.value, int | float):
        raise ValueError("field-test result must contain a numeric scalar")
    return _finite(value.value, "field-test result")


def _structured_reference(
    observation: ScientificMeasurementObservation,
) -> StructuredOutputReference:
    value = observation.result.value
    if not isinstance(value, StructuredOutputReference):
        raise ValueError("field-test source observation must reference a structured artifact")
    return value


def _unique_by_id[T](values: Iterable[T], identifier: str | Callable[[T], object]) -> tuple[T, ...]:
    """Deduplicate immutable lineage values while rejecting same-ID conflicts."""

    result: dict[str, T] = {}
    for value in values:
        key_value = getattr(value, identifier) if isinstance(identifier, str) else identifier(value)
        key = key_value.qualified if isinstance(key_value, InstanceIdentifier) else str(key_value)
        previous = result.get(key)
        if previous is not None and previous != value:
            raise ValueError(f"lineage ID {key!r} has conflicting immutable content")
        result[key] = value
    return tuple(result.values())


def _merge_provenance(provenances: Iterable[Provenance]) -> Provenance:
    items = tuple(provenances)
    if not items:
        raise ValueError("at least one provenance record is required")
    artifacts = _unique_by_id(
        (artifact for provenance in items for artifact in provenance.source_artifacts),
        "artifact_id",
    )
    acquisitions = _unique_by_id(
        (acquisition for provenance in items for acquisition in provenance.acquisitions),
        "acquisition_id",
    )
    processing_runs = _unique_by_id(
        (run for provenance in items for run in provenance.processing_runs),
        "processing_run_id",
    )
    edges = _unique_by_id(
        (edge for provenance in items for edge in provenance.lineage_edges),
        lambda edge: (edge.from_id, edge.to_id, edge.relation.value),
    )
    evidence = tuple(
        dict.fromkeys(
            evidence_reference
            for provenance in items
            for evidence_reference in provenance.evidence_references
        )
    )
    traceability = tuple(
        dict.fromkeys(
            reference for provenance in items for reference in provenance.metrological_traceability
        )
    )
    recorded_at = next(
        (provenance.recorded_at for provenance in items if provenance.recorded_at is not None),
        None,
    )
    return Provenance(
        provenance_id=items[0].provenance_id,
        source_artifacts=tuple(sorted(artifacts, key=lambda item: item.artifact_id.qualified)),
        acquisitions=tuple(sorted(acquisitions, key=lambda item: item.acquisition_id.qualified)),
        processing_runs=tuple(
            sorted(processing_runs, key=lambda item: item.processing_run_id.qualified)
        ),
        lineage_edges=tuple(
            sorted(edges, key=lambda item: (item.from_id, item.to_id, item.relation.value))
        ),
        evidence_references=evidence,
        metrological_traceability=traceability,
        recorded_at=recorded_at,
    )


def _provenance_with_run(
    base: Provenance,
    *,
    processing_run: ProcessingRun,
    output_entity_id: InstanceIdentifier,
    source_entity_ids: tuple[InstanceIdentifier, ...],
    output_artifact: SourceArtifact,
    evidence_references: tuple[EvidenceReference, ...] = (),
) -> Provenance:
    artifacts = _unique_by_id(
        (*base.source_artifacts, output_artifact),
        "artifact_id",
    )
    runs = _unique_by_id((*base.processing_runs, processing_run), "processing_run_id")
    edges = list(base.lineage_edges)
    for source_id in source_entity_ids:
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
    for acquisition in base.acquisitions:
        edge = LineageEdge(
            acquisition.acquisition_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    output_artifact_edge = LineageEdge(
        processing_run.processing_run_id.qualified,
        output_artifact.artifact_id.qualified,
        LineageRelation.PRODUCED,
    )
    if output_artifact_edge not in edges:
        edges.append(output_artifact_edge)
    for evidence_reference in evidence_references:
        edge = LineageEdge(
            evidence_reference.reference.stable_id,
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
        source_artifacts=tuple(sorted(artifacts, key=lambda item: item.artifact_id.qualified)),
        acquisitions=base.acquisitions,
        processing_runs=tuple(sorted(runs, key=lambda item: item.processing_run_id.qualified)),
        lineage_edges=tuple(
            sorted(edges, key=lambda item: (item.from_id, item.to_id, item.relation.value))
        ),
        evidence_references=tuple(dict.fromkeys((*base.evidence_references, *evidence_references))),
        metrological_traceability=base.metrological_traceability,
        recorded_at=base.recorded_at,
    )


def _multisource_context(
    operation: RegistryReference,
    observations: tuple[ScientificMeasurementObservation, ...],
) -> ObservationContext:
    """Use RES-66 context authority, with a deterministic cross-test extension."""

    if len(observations) == 1:
        return observations[0].context
    observation_ids = tuple(item.observation_id for item in observations)
    if len(set(observation_ids)) != len(observation_ids):
        raise ValueError("multi-source context observations must be unique")
    from dynamislm.measurement.strength.context import build_multisource_analysis_context

    try:
        return build_multisource_analysis_context(operation, observations)
    except ValueError as exc:
        first = observations[0].context
        if any(
            observation.context.athlete_id != first.athlete_id
            or observation.context.session_id != first.session_id
            or observation.context.observed_at != first.observed_at
            or observation.context.population_context != first.population_context
            or observation.context.environment != first.environment
            for observation in observations[1:]
        ):
            raise exc
        source_context_ids = tuple(
            sorted(observation.context.context_id.qualified for observation in observations)
        )
        source_test_ids = tuple(
            sorted(observation.context.test_instance_id.qualified for observation in observations)
        )
        digest = canonical_hash(
            {
                "operation": operation,
                "source_observation_ids": tuple(
                    sorted(observation.observation_id.qualified for observation in observations)
                ),
                "source_context_ids": source_context_ids,
                "source_test_instance_ids": source_test_ids,
            }
        ).removeprefix("sha256:")[:32]
        return ObservationContext(
            context_id=InstanceIdentifier("context", f"res67-multisource:{digest}"),
            athlete_id=first.athlete_id,
            session_id=first.session_id,
            test_instance_id=InstanceIdentifier("test-instance", f"res67-multisource:{digest}"),
            trial_id=None,
            observed_at=first.observed_at,
            population_context=first.population_context,
            environment=first.environment,
            context_metadata=(
                MetadataEntry("analysis_operation", operation.stable_id),
                MetadataEntry("source_context_ids", canonical_json(source_context_ids)),
                MetadataEntry(
                    "source_observation_ids",
                    canonical_json(
                        tuple(
                            sorted(
                                observation.observation_id.qualified for observation in observations
                            )
                        )
                    ),
                ),
                MetadataEntry("source_test_instance_ids", canonical_json(source_test_ids)),
            ),
        )


def _require_verified_field_artifact(artifact: FieldTestingSourceArtifact) -> None:
    if not isinstance(artifact, FieldTestingSourceArtifact):
        raise ValueError("field-test source artifact must use the typed artifact contract")
    if not artifact.immutable or artifact.status is not FieldTestArtifactStatus.VERIFIED:
        raise ValueError("field-test source artifact must be immutable and verified")


def build_field_testing_source_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: FieldTestingMeasurementIdentity,
    result: MeasurementResult,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    processing_run: ProcessingRun | None = None,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Create a verified field-test source observation with full lineage."""

    _require_verified_field_artifact(source_artifact)
    if not isinstance(context, ObservationContext):
        raise ValueError("context must be an ObservationContext")
    if not isinstance(identity, FieldTestingMeasurementIdentity):
        raise ValueError("identity must be a FieldTestingMeasurementIdentity")
    if not isinstance(result, MeasurementResult):
        raise ValueError("result must be a MeasurementResult")
    if not isinstance(acquisition, FieldTestingAcquisitionRecord):
        raise ValueError("acquisition must be a FieldTestingAcquisitionRecord")
    if identity.acquisition.raw_artifact != source_artifact.artifact_id:
        raise ValueError("identity raw artifact does not match source artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("identity acquisition does not match acquisition record")
    if acquisition.source_artifact_id != source_artifact.artifact_id:
        raise ValueError("acquisition does not reference source artifact")
    acquisition_identity = identity.acquisition
    if (
        acquisition_identity.device != acquisition.device
        or acquisition_identity.provider != acquisition.provider
        or acquisition_identity.sensor_modality != acquisition.sensor_modality
        or acquisition_identity.sensor_channel != acquisition.sensor_channel
        or acquisition_identity.sampling != acquisition.sampling
        or acquisition_identity.calibration_reference != acquisition.calibration_reference
        or acquisition_identity.hardware_firmware != acquisition.hardware_firmware
        or acquisition_identity.axis_or_frame != acquisition.axis_or_frame
    ):
        raise ValueError("identity and acquisition record do not describe the same system")
    if processing_run is None:
        processing_run = ProcessingRun(
            processing_run_id=InstanceIdentifier(
                "processing-run", f"field-test-source:{observation_id.value}"
            ),
            source_artifact_ids=(source_artifact.artifact_id,),
            method=identity.version.processing_method,
            parameters=identity.processing.method_parameters,
            software_version=identity.version.software_version,
            output_entity_id=observation_id,
        )
    if processing_run.output_entity_id != observation_id:
        raise ValueError("source processing run output must match observation ID")
    if source_artifact.artifact_id not in processing_run.source_artifact_ids:
        raise ValueError("source processing run must reference source artifact")
    if processing_run.method != identity.version.processing_method:
        raise ValueError("source processing run method does not match identity")
    if processing_run.parameters != identity.processing.method_parameters:
        raise ValueError("source processing run parameters do not match identity")
    if processing_run.software_version != identity.version.software_version:
        raise ValueError("source processing run software version does not match identity")
    source_origin = result.classification.value_origin
    processing_state = identity.processing.processing_state
    if (
        processing_state is FieldTestProcessingState.PROVIDER_PROCESSED
        and source_origin is not ValueOrigin.PROVIDER_DERIVED
    ):
        raise ValueError("provider-processed source output must remain provider-derived")
    if (
        processing_state is FieldTestProcessingState.DYNAMISLM_PROCESSED
        and source_origin is not ValueOrigin.DYNAMISLM_DERIVED
    ):
        raise ValueError("DynamisLM-processed source output must remain derived")
    return create_derived_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        processing_run=processing_run,
        evidence_references=evidence_references,
        recorded_at=recorded_at,
    )


def _build_derived_observation(
    *,
    source_observations: tuple[ScientificMeasurementObservation, ...],
    identity: FieldTestingMeasurementIdentity,
    value: float,
    unit: UnitReference,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    output_observation_id: InstanceIdentifier | None = None,
    value_origin: ValueOrigin = ValueOrigin.DYNAMISLM_DERIVED,
    scientific_roles: tuple[ScientificRole, ...] = (ScientificRole.PERFORMANCE_OUTCOME,),
    evidence_references: tuple[EvidenceReference, ...] = (),
    extra_source_entities: tuple[InstanceIdentifier, ...] = (),
    media_type: str = "application/vnd.dynamislm.field-testing.scalar-metric",
) -> ScientificMeasurementObservation:
    if not source_observations:
        raise ValueError("derived field-test output requires source observations")
    if any(not isinstance(item, ScientificMeasurementObservation) for item in source_observations):
        raise ValueError("source_observations must contain scientific observations")
    source_ids = tuple(item.observation_id for item in source_observations)
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("derived field-test output sources must be unique")
    if not isinstance(identity, FieldTestingMeasurementIdentity):
        raise ValueError("derived identity must be a FieldTestingMeasurementIdentity")
    if not isinstance(operation, RegistryReference):
        raise ValueError("operation must be a RegistryReference")
    numeric_value = _finite(value, "derived value")
    digest = canonical_hash(
        {
            "operation": operation,
            "parameters": parameters,
            "value": numeric_value,
            "source_observation_ids": tuple(sorted(item.qualified for item in source_ids)),
        }
    ).removeprefix("sha256:")[:24]
    output_id = output_observation_id or InstanceIdentifier(
        "observation", f"field-test:{operation.identifier.key}:{digest}"
    )
    if output_id in source_ids:
        raise ValueError("derived field-test observation must differ from every source")
    base = _merge_provenance(item.provenance for item in source_observations)
    source_artifact_ids = tuple(
        sorted(
            (artifact.artifact_id for artifact in base.source_artifacts),
            key=lambda item: item.qualified,
        )
    )
    if not source_artifact_ids:
        raise ValueError("derived field-test output requires source artifacts")
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"field-test:{operation.identifier.key}:{digest}"
        ),
        source_artifact_ids=source_artifact_ids,
        method=operation,
        parameters=parameters,
        software_version=FIELD_TESTING_SOFTWARE_VERSION,
        output_entity_id=output_id,
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"field-test-result:{digest}"),
        content_digest=canonical_hash(
            {"identity": identity, "value": numeric_value, "unit": unit, "parameters": parameters}
        ),
        media_type=media_type,
        immutable=True,
    )
    evidence = tuple(
        dict.fromkeys((EvidenceReference(RES67_DECISION_FIELD_TESTING), *evidence_references))
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=output_id,
        source_entity_ids=tuple((*source_ids, *extra_source_entities)),
        output_artifact=output_artifact,
        evidence_references=evidence,
    )
    context = _multisource_context(operation, source_observations)
    return ScientificMeasurementObservation(
        observation_id=output_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier(
                "result", f"field-test:{operation.identifier.key}:{digest}"
            ),
            value=ScalarValue(numeric_value),
            unit=unit,
            classification=ScientificClassification(value_origin, scientific_roles),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=(
                    "RES-67 deterministic arithmetic; measurement uncertainty is not assessed."
                ),
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingScalarResult:
    """One registered scalar field-test output and its exact source set."""

    observation: ScientificMeasurementObservation
    metric: RegistryReference
    source_observations: tuple[ScientificMeasurementObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.observation, ScientificMeasurementObservation):
            raise ValueError("observation must be a ScientificMeasurementObservation")
        if not isinstance(self.metric, RegistryReference):
            raise ValueError("metric must be a RegistryReference")
        _require_tuple_items(
            self.source_observations,
            ScientificMeasurementObservation,
            "source_observations",
        )
        if not isinstance(self.observation.identity, FieldTestingMeasurementIdentity):
            raise ValueError("field-test scalar result requires field-testing identity")
        if self.observation.identity.semantic.metric_definition != self.metric:
            raise ValueError("field-test scalar result metric does not match identity")
        _numeric_scalar(self.observation)
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("field-test scalar result must be valid")
        output_runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(output_runs) != 1:
            raise ValueError("field-test scalar result must preserve one output processing run")
        source_ids = {item.observation_id.qualified for item in self.source_observations}
        for source_id in source_ids:
            if not any(
                edge.from_id == source_id
                and edge.to_id == output_runs[0].processing_run_id.qualified
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("field-test scalar result is missing source lineage")

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def result(self) -> MeasurementResult:
        return self.observation.result

    @property
    def context(self) -> ObservationContext:
        return self.observation.context

    @property
    def identity(self) -> MeasurementIdentity:
        return self.observation.identity


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingSourceQualificationEvidence:
    """Source-reported categorical qualification bound to one target observation."""

    target_observation_id: InstanceIdentifier
    qualification_observation: ScientificMeasurementObservation
    qualification_reference: RegistryReference

    def __post_init__(self) -> None:
        _require_instance(self.target_observation_id, InstanceIdentifier, "target_observation_id")
        if self.target_observation_id.instance_type != "observation":
            raise ValueError("target_observation_id must identify an observation")
        if not isinstance(self.qualification_observation, ScientificMeasurementObservation):
            raise ValueError("qualification_observation must be a scientific observation")
        _require_instance(
            self.qualification_reference, RegistryReference, "qualification_reference"
        )
        if self.qualification_reference != FIELD_TEST_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("qualification reference is not the registered source rule")
        value = self.qualification_observation.result.value
        if not isinstance(value, CategoricalValue):
            raise ValueError("qualification observation must carry a categorical source result")
        try:
            FieldTestQualificationStatus(value.category)
        except ValueError as exc:
            raise ValueError("qualification category is not registered") from exc
        if (
            self.qualification_observation.result.classification.value_origin
            is not ValueOrigin.SOURCE_REPORTED
        ):
            raise ValueError("qualification must remain source-reported")
        if self.qualification_observation.result.status is not ResultStatus.VALID:
            raise ValueError("qualification observation must be valid")
        identity = self.qualification_observation.identity
        if not isinstance(identity, FieldTestingMeasurementIdentity):
            raise ValueError("qualification observation requires field-testing identity")
        if identity.semantic.measurand != FIELD_TEST_QUALIFICATION_MEASURAND:
            raise ValueError("qualification observation has the wrong measurand")
        if identity.semantic.metric_definition != FIELD_TEST_QUALIFICATION_METRIC:
            raise ValueError("qualification observation has the wrong metric")
        if identity.processing.registered_operation != FIELD_TEST_SOURCE_QUALIFICATION_OPERATION:
            raise ValueError("qualification observation has the wrong operation")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if parameters.get("target_observation_id") != self.target_observation_id.qualified:
            raise ValueError("qualification evidence target is not preserved in source identity")

    @property
    def status(self) -> FieldTestQualificationStatus:
        value = self.qualification_observation.result.value
        assert isinstance(value, CategoricalValue)
        return FieldTestQualificationStatus(value.category)

    @property
    def source_observation_id(self) -> InstanceIdentifier:
        return self.qualification_observation.observation_id


def build_source_qualification_observation(
    *,
    target_observation: ScientificMeasurementObservation,
    status: FieldTestQualificationStatus,
    source_artifact: FieldTestingSourceArtifact,
    acquisition: FieldTestingAcquisitionRecord,
    output_observation_id: InstanceIdentifier | None = None,
    recorded_at: datetime_module.datetime | None = None,
) -> FieldTestingSourceQualificationEvidence:
    """Normalize source-reported qualification without running a QC algorithm."""

    if not isinstance(target_observation, ScientificMeasurementObservation):
        raise ValueError("target_observation must be a scientific observation")
    if not isinstance(status, FieldTestQualificationStatus):
        raise ValueError("status must be a FieldTestQualificationStatus")
    target_identity = target_observation.identity
    if not isinstance(target_identity, FieldTestingMeasurementIdentity):
        raise ValueError("target observation requires field-testing identity")
    qualification_identity = FieldTestingMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"field-test-qualification:{target_observation.observation_id.value}",
            FIELD_TESTING_REGISTRY_VERSION,
        ),
        semantic=FieldTestingSemanticIdentity(
            construct=target_identity.semantic.construct,
            test_family=target_identity.semantic.test_family,
            protocol=target_identity.semantic.protocol,
            measurand=FIELD_TEST_QUALIFICATION_MEASURAND,
            metric_definition=FIELD_TEST_QUALIFICATION_METRIC,
            protocol_identity=target_identity.semantic.protocol_identity,
        ),
        acquisition=target_identity.acquisition,
        processing=FieldTestingProcessingIdentity(
            registered_operation=FIELD_TEST_SOURCE_QUALIFICATION_OPERATION,
            method_parameters=(
                MetadataEntry("target_observation_id", target_observation.observation_id.qualified),
                MetadataEntry("source_status", status.value),
            ),
            processing_state=FieldTestProcessingState.RAW_ACQUIRED,
        ),
        version=VersionIdentity(
            processing_method=FIELD_TEST_SOURCE_QUALIFICATION_OPERATION,
            method_registry_version=FIELD_TESTING_REGISTRY_VERSION,
            software_version=FIELD_TESTING_SOFTWARE_VERSION,
            hardware_firmware=target_identity.version.hardware_firmware,
        ),
    )
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"field-test-qualification:{target_observation.observation_id.value}"
    )
    result = MeasurementResult(
        result_id=InstanceIdentifier("result", f"field-test-qualification:{observation_id.value}"),
        value=CategoricalValue(status.value),
        unit=None,
        classification=ScientificClassification(ValueOrigin.SOURCE_REPORTED, ()),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
        status=ResultStatus.VALID,
    )
    observation = build_field_testing_source_observation(
        observation_id=observation_id,
        context=target_observation.context,
        identity=qualification_identity,
        result=result,
        source_artifact=source_artifact,
        acquisition=acquisition,
        evidence_references=(EvidenceReference(RES67_DECISION_FIELD_TESTING),),
        recorded_at=recorded_at,
    )
    return FieldTestingSourceQualificationEvidence(
        target_observation_id=target_observation.observation_id,
        qualification_observation=observation,
        qualification_reference=FIELD_TEST_SOURCE_QUALIFICATION_OPERATION,
    )


def _require_qualified(
    evidence: FieldTestingSourceQualificationEvidence,
    target_observation: ScientificMeasurementObservation,
) -> None:
    if not isinstance(evidence, FieldTestingSourceQualificationEvidence):
        raise ValueError("source qualification evidence is required")
    if evidence.target_observation_id != target_observation.observation_id:
        raise ValueError("source qualification targets a different observation")
    if evidence.status is not FieldTestQualificationStatus.QUALIFIED:
        raise ValueError("source observation is not source-qualified")
    target_artifact_ids = {
        item.artifact_id for item in target_observation.provenance.source_artifacts
    }
    qualification_artifact_ids = {
        item.artifact_id for item in evidence.qualification_observation.provenance.source_artifacts
    }
    if not qualification_artifact_ids.issubset(target_artifact_ids):
        raise ValueError("qualification evidence uses a different source artifact")
    target_acquisition_ids = {
        item.acquisition_id for item in target_observation.provenance.acquisitions
    }
    qualification_acquisition_ids = {
        item.acquisition_id for item in evidence.qualification_observation.provenance.acquisitions
    }
    if not qualification_acquisition_ids.issubset(target_acquisition_ids):
        raise ValueError("qualification evidence uses a different source acquisition")
    left = evidence.qualification_observation.context
    right = target_observation.context
    if (
        left.athlete_id != right.athlete_id
        or left.session_id != right.session_id
        or left.test_instance_id != right.test_instance_id
        or left.observed_at != right.observed_at
        or left.environment != right.environment
    ):
        raise ValueError("qualification context does not match target observation")


def _refusal(
    claim: str,
    reason_codes: tuple[RefusalReasonCode | str, ...],
    missing_information: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.IDENTITY_UNRESOLVED,
    safe_descriptions: tuple[str, ...] = (),
) -> RefusalResult:
    codes = tuple(
        code.value if isinstance(code, RefusalReasonCode) else code for code in reason_codes
    )
    digest = canonical_hash(
        {
            "claim": claim,
            "reason_codes": codes,
            "missing_information": missing_information,
            "observation_ids": observation_ids,
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"field-test:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions,
        evidence_references=(RES67_DECISION_FIELD_TESTING,),
        observation_ids=observation_ids,
    )


__all__ = [
    "FieldTestingScalarResult",
    "FieldTestingSourceQualificationEvidence",
    "_build_derived_observation",
    "_finite",
    "_merge_provenance",
    "_multisource_context",
    "_numeric_scalar",
    "_protocol_processing_components",
    "_provenance_with_run",
    "_refusal",
    "_require_qualified",
    "_structured_reference",
    "build_field_testing_source_observation",
    "build_source_qualification_observation",
]
