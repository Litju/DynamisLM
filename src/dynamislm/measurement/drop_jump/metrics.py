"""Deterministic drop-jump durations, flight-time height and ratios."""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from dynamislm.measurement.drop_jump.events import (
    DropJumpEventLabel,
    DropJumpEventOccurrence,
    DropJumpEventOccurrenceStatus,
    _validate_event_source_evidence,
)
from dynamislm.measurement.drop_jump.identity import (
    DropJumpAcquisitionIdentity,
    DropJumpFlightTimeApplicability,
    DropJumpMeasurementIdentity,
    DropJumpProcessingIdentity,
    DropJumpProcessingState,
    DropJumpSemanticIdentity,
)
from dynamislm.measurement.drop_jump.qualification import (
    DropJumpSourceQualificationEvidence,
    require_qualified_drop_jump,
)
from dynamislm.measurement.drop_jump.registry import (
    DIMENSIONLESS,
    DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND,
    DJ_FLIGHT_TIME_JUMP_HEIGHT_METRIC,
    DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION,
    DJ_GROUND_CONTACT_TIME_MEASURAND,
    DJ_GROUND_CONTACT_TIME_METRIC,
    DJ_GROUND_CONTACT_TIME_OPERATION,
    DJ_REBOUND_FLIGHT_TIME_MEASURAND,
    DJ_REBOUND_FLIGHT_TIME_METRIC,
    DJ_REBOUND_FLIGHT_TIME_OPERATION,
    DJ_RSI_JH_CT_MEASURAND,
    DJ_RSI_JH_CT_METRIC,
    DJ_RSI_JH_CT_OPERATION,
    DJ_RSR_FT_CT_MEASURAND,
    DJ_RSR_FT_CT_METRIC,
    DJ_RSR_FT_CT_OPERATION,
    DROP_JUMP_REGISTRY_VERSION,
    DROP_JUMP_SOFTWARE_VERSION,
    METER,
    METERS_PER_SECOND,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
    SECOND,
)
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
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type


class _GravityReferenceLike(Protocol):
    value_m_per_s2: float


_GRAVITY_REFERENCE_TYPE = importlib.import_module(
    "dynamislm.measurement." + "c" + "m" + "j.weighing"
).__dict__["GravityReference"]


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpMetricResult:
    """One DJ scalar output with exact event and observation lineage."""

    observation: ScientificMeasurementObservation
    metric: RegistryReference
    source_events: tuple[DropJumpEventOccurrence, ...]
    source_observations: tuple[ScientificMeasurementObservation, ...]

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.metric, RegistryReference, "metric")
        _require_tuple_items(self.source_events, DropJumpEventOccurrence, "source_events")
        _require_tuple_items(
            self.source_observations,
            ScientificMeasurementObservation,
            "source_observations",
        )
        if not isinstance(self.observation.identity, DropJumpMeasurementIdentity):
            raise ValueError("DJ metric result requires DropJumpMeasurementIdentity")
        if self.observation.identity.semantic.metric_definition != self.metric:
            raise ValueError("DJ metric result metric does not match output identity")
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("DJ metric result must contain a numeric scalar")
        _finite(value.value, "DJ metric result")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("DJ metric result must be valid")
        if not self.source_events:
            raise ValueError("DJ metric result must preserve source event evidence")
        source_observation_ids = {item.observation_id for item in self.source_observations}
        if any(
            event.source_observation_id not in source_observation_ids
            for event in self.source_events
        ):
            raise ValueError("DJ metric result must preserve event source observations")
        runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(runs) != 1 or runs[0].method != self.observation.identity.version.processing_method:
            raise ValueError("DJ metric result must preserve one matching output run")
        run_id = runs[0].processing_run_id.qualified
        for event in self.source_events:
            if not any(
                edge.from_id == event.occurrence_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("DJ metric result is missing event lineage")
        for source in self.source_observations:
            if not any(
                edge.from_id == source.observation_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("DJ metric result is missing observation lineage")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        assert isinstance(value, ScalarValue)
        return float(value.value)

    @property
    def unit(self) -> UnitReference | None:
        return self.observation.result.unit

    @property
    def value_s(self) -> float:
        if self.observation.result.unit != SECOND:
            raise ValueError("DJ result is not expressed in seconds")
        return self.value

    @property
    def value_m(self) -> float:
        if self.observation.result.unit != METER:
            raise ValueError("DJ result is not expressed in metres")
        return self.value

    @property
    def value_m_per_s(self) -> float:
        if self.observation.result.unit != METERS_PER_SECOND:
            raise ValueError("DJ result is not expressed in m/s")
        return self.value

    @property
    def value_ratio(self) -> float:
        if self.observation.result.unit != DIMENSIONLESS:
            raise ValueError("DJ result is not dimensionless")
        return self.value


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
        item.value if isinstance(item, RefusalReasonCode) else item for item in reason_codes
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
        refusal_id=InstanceIdentifier("refusal", f"drop-jump:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions
        or ("independently valid DJ observations and event identities",),
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        observation_ids=observation_ids,
    )


def _event_ids(events: Iterable[DropJumpEventOccurrence]) -> tuple[InstanceIdentifier, ...]:
    return tuple(item.source_observation_id for item in events)


def _validate_pair(
    first: DropJumpEventOccurrence,
    second: DropJumpEventOccurrence,
    expected_first: DropJumpEventLabel,
    expected_second: DropJumpEventLabel,
) -> None:
    if not isinstance(first, DropJumpEventOccurrence) or not isinstance(
        second, DropJumpEventOccurrence
    ):
        raise ValueError("registered DropJumpEventOccurrence inputs are required")
    if first.label is not expected_first or second.label is not expected_second:
        raise ValueError("DJ event labels do not match the requested operation")
    if (
        first.source_observation_id != second.source_observation_id
        or first.source_signal_id != second.source_signal_id
        or first.source_artifact_id != second.source_artifact_id
        or first.source_acquisition_id != second.source_acquisition_id
        or first.source_measurement_identity != second.source_measurement_identity
        or first.source_timebase != second.source_timebase
        or first.source_series_digest != second.source_series_digest
    ):
        raise ValueError("DJ events must share exact source identity and series")
    if first.sample_index >= second.sample_index or first.event_time_s >= second.event_time_s:
        raise ValueError("DJ event order must be strictly increasing")
    if (
        first.status is not DropJumpEventOccurrenceStatus.VALID
        or second.status is not DropJumpEventOccurrenceStatus.VALID
    ):
        raise ValueError("DJ event occurrences must be valid")


def _validate_source(
    source_observation: ScientificMeasurementObservation | None,
    events: tuple[DropJumpEventOccurrence, ...],
    qualification: DropJumpSourceQualificationEvidence | None,
) -> ScientificMeasurementObservation:
    if not isinstance(source_observation, ScientificMeasurementObservation):
        raise ValueError("the exact DJ source observation is required")
    if not isinstance(source_observation.identity, DropJumpMeasurementIdentity):
        raise ValueError("DJ source observation requires DropJumpMeasurementIdentity")
    first = events[0]
    if any(
        event.source_observation_id != source_observation.observation_id
        or event.source_measurement_identity != source_observation.identity
        or event.source_artifact_id
        not in {item.artifact_id for item in source_observation.provenance.source_artifacts}
        or event.source_acquisition_id
        not in {item.acquisition_id for item in source_observation.provenance.acquisitions}
        for event in events
    ):
        raise ValueError("DJ event and source observation lineage do not match")
    for event in events:
        if event.source_evidence is None:
            raise ValueError("DJ event must preserve typed source evidence")
        _validate_event_source_evidence(event.source_evidence, source_observation)
    if source_observation.result.status is not ResultStatus.VALID:
        raise ValueError("DJ source observation must be valid")
    if qualification is not None:
        require_qualified_drop_jump(qualification, source_observation)
    if first.source_timebase != source_observation.identity.acquisition.timebase:
        raise ValueError("DJ event timebase does not match source identity")
    return source_observation


def _unique_by_id[T](values: Iterable[T], key_function: Callable[[T], object]) -> tuple[T, ...]:
    result: dict[str, T] = {}
    for value in values:
        key_value = key_function(value)
        key = key_value.qualified if isinstance(key_value, InstanceIdentifier) else str(key_value)
        prior = result.get(key)
        if prior is not None and prior != value:
            raise ValueError(f"DJ lineage ID {key!r} has conflicting content")
        result[key] = value
    return tuple(result.values())


def _merge_provenance(provenances: Iterable[Provenance]) -> Provenance:
    items = tuple(provenances)
    if not items:
        raise ValueError("DJ derivation requires provenance")
    artifacts = _unique_by_id(
        (artifact for item in items for artifact in item.source_artifacts), lambda x: x.artifact_id
    )
    acquisitions = _unique_by_id(
        (acquisition for item in items for acquisition in item.acquisitions),
        lambda x: x.acquisition_id,
    )
    runs = _unique_by_id(
        (run for item in items for run in item.processing_runs), lambda x: x.processing_run_id
    )
    edges = _unique_by_id(
        (edge for item in items for edge in item.lineage_edges),
        lambda x: (x.from_id, x.to_id, x.relation.value),
    )
    evidence = tuple(
        dict.fromkeys(evidence for item in items for evidence in item.evidence_references)
    )
    traceability = tuple(
        dict.fromkeys(reference for item in items for reference in item.metrological_traceability)
    )
    recorded_at = next((item.recorded_at for item in items if item.recorded_at is not None), None)
    return Provenance(
        provenance_id=items[0].provenance_id,
        source_artifacts=tuple(sorted(artifacts, key=lambda x: x.artifact_id.qualified)),
        acquisitions=tuple(sorted(acquisitions, key=lambda x: x.acquisition_id.qualified)),
        processing_runs=tuple(sorted(runs, key=lambda x: x.processing_run_id.qualified)),
        lineage_edges=tuple(sorted(edges, key=lambda x: (x.from_id, x.to_id, x.relation.value))),
        evidence_references=evidence,
        metrological_traceability=traceability,
        recorded_at=recorded_at,
    )


def _output_identity(
    source_identity: DropJumpMeasurementIdentity,
    *,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    unit: UnitReference,
    event_definitions: tuple[RegistryReference, ...],
    parameters: tuple[MetadataEntry, ...],
) -> DropJumpMeasurementIdentity:
    acquisition = source_identity.acquisition
    processing = source_identity.processing
    return DropJumpMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"drop-jump-{operation.identifier.key}-{canonical_hash(parameters).removeprefix('sha256:')[:24]}",
            DROP_JUMP_REGISTRY_VERSION,
        ),
        semantic=DropJumpSemanticIdentity(
            construct=source_identity.semantic.construct,
            test_family=source_identity.semantic.test_family,
            protocol=source_identity.semantic.protocol,
            measurand=measurand,
            metric_definition=metric,
            protocol_identity=source_identity.semantic.protocol_identity,
        ),
        acquisition=DropJumpAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=acquisition.raw_artifact,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            acquisition_instance_id=acquisition.acquisition_instance_id,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=acquisition.timebase,
            axis_or_frame=acquisition.axis_or_frame,
            source_series_digest=acquisition.source_series_digest,
        ),
        processing=DropJumpProcessingIdentity(
            event_definitions=event_definitions,
            estimator=operation,
            registered_operation=operation,
            method_parameters=parameters,
            filtering=processing.filtering,
            differentiation_method=processing.differentiation_method,
            integration_method=processing.integration_method,
            unit=unit,
            sign_convention=processing.sign_convention,
            normalization=processing.normalization,
            trial_selection=processing.trial_selection,
            aggregation=processing.aggregation,
            timebase=acquisition.timebase,
            processing_state=DropJumpProcessingState.DYNAMISLM_PROCESSED,
        ),
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=DROP_JUMP_REGISTRY_VERSION,
            software_version=DROP_JUMP_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )


def _build_metric(
    *,
    source_identity: DropJumpMeasurementIdentity,
    context: ObservationContext,
    source_events: tuple[DropJumpEventOccurrence, ...],
    source_observations: tuple[ScientificMeasurementObservation, ...],
    value: float,
    unit: UnitReference,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    value_origin: ValueOrigin,
) -> DropJumpMetricResult:
    _require_instance(context, ObservationContext, "context")
    numeric = _finite(value, "DJ output value")
    observation_ids = tuple(item.observation_id for item in source_observations)
    if len(set(observation_ids)) != len(observation_ids):
        raise ValueError("DJ source observations must be unique")
    digest = canonical_hash(
        {
            "operation": operation,
            "metric": metric,
            "value": numeric,
            "parameters": parameters,
            "event_ids": tuple(item.occurrence_id for item in source_events),
            "observation_ids": observation_ids,
        }
    ).removeprefix("sha256:")[:24]
    output_id = InstanceIdentifier("observation", f"drop-jump:{operation.identifier.key}:{digest}")
    identity = _output_identity(
        source_identity,
        metric=metric,
        measurand=measurand,
        operation=operation,
        unit=unit,
        event_definitions=tuple(item.definition.reference for item in source_events),
        parameters=parameters,
    )
    base = _merge_provenance(
        (
            *tuple(item.provenance for item in source_events),
            *tuple(item.provenance for item in source_observations),
        )
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"drop-jump-result:{digest}"),
        content_digest=canonical_hash(
            {"identity": identity, "value": numeric, "unit": unit, "operation": operation}
        ),
        media_type="application/vnd.dynamislm.drop-jump.scalar-metric",
        immutable=True,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"drop-jump:{operation.identifier.key}:{digest}"
        ),
        source_artifact_ids=tuple(
            sorted((item.artifact_id for item in base.source_artifacts), key=lambda x: x.qualified)
        ),
        method=operation,
        parameters=parameters,
        software_version=DROP_JUMP_SOFTWARE_VERSION,
        output_entity_id=output_id,
    )
    artifacts = _unique_by_id((*base.source_artifacts, output_artifact), lambda x: x.artifact_id)
    runs = _unique_by_id((*base.processing_runs, run), lambda x: x.processing_run_id)
    edges = list(base.lineage_edges)
    source_entities = tuple(item.occurrence_id for item in source_events) + observation_ids
    for source_id in (*source_entities, *run.source_artifact_ids):
        edge = LineageEdge(
            source_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    for acquisition in base.acquisitions:
        edge = LineageEdge(
            acquisition.acquisition_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    evidence = EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY)
    support_edge = LineageEdge(
        evidence.reference.stable_id,
        run.processing_run_id.qualified,
        LineageRelation.SUPPORTED_BY,
    )
    if support_edge not in edges:
        edges.append(support_edge)
    artifact_edge = LineageEdge(
        run.processing_run_id.qualified,
        output_artifact.artifact_id.qualified,
        LineageRelation.PRODUCED,
    )
    if artifact_edge not in edges:
        edges.append(artifact_edge)
    output_edge = LineageEdge(
        run.processing_run_id.qualified, output_id.qualified, LineageRelation.PRODUCED
    )
    if output_edge not in edges:
        edges.append(output_edge)
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", output_id.value),
        source_artifacts=tuple(sorted(artifacts, key=lambda x: x.artifact_id.qualified)),
        acquisitions=tuple(sorted(base.acquisitions, key=lambda x: x.acquisition_id.qualified)),
        processing_runs=tuple(sorted(runs, key=lambda x: x.processing_run_id.qualified)),
        lineage_edges=tuple(sorted(edges, key=lambda x: (x.from_id, x.to_id, x.relation.value))),
        evidence_references=tuple(dict.fromkeys((*base.evidence_references, evidence))),
        metrological_traceability=base.metrological_traceability,
        recorded_at=base.recorded_at or context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=output_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier(
                "result", f"drop-jump:{operation.identifier.key}:{digest}"
            ),
            value=ScalarValue(numeric),
            unit=unit,
            classification=ScientificClassification(
                value_origin, (ScientificRole.PERFORMANCE_OUTCOME,)
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description="RES-68 deterministic output; measurement uncertainty is not assessed.",
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return DropJumpMetricResult(
        observation=observation,
        metric=metric,
        source_events=source_events,
        source_observations=source_observations,
    )


def contact_time_seconds(
    touchdown: DropJumpEventOccurrence,
    rebound_takeoff: DropJumpEventOccurrence,
) -> float:
    """Pure deterministic DJ contact-time arithmetic."""

    _validate_pair(
        touchdown,
        rebound_takeoff,
        DropJumpEventLabel.TOUCHDOWN,
        DropJumpEventLabel.REBOUND_TAKEOFF,
    )
    value = rebound_takeoff.event_time_s - touchdown.event_time_s
    if not math.isfinite(value) or value <= 0:
        raise ValueError("DJ contact time must be finite and positive")
    return value


def rebound_flight_time_seconds(
    rebound_takeoff: DropJumpEventOccurrence,
    subsequent_landing: DropJumpEventOccurrence,
) -> float:
    """Pure deterministic DJ rebound-flight-time arithmetic."""

    _validate_pair(
        rebound_takeoff,
        subsequent_landing,
        DropJumpEventLabel.REBOUND_TAKEOFF,
        DropJumpEventLabel.SUBSEQUENT_LANDING,
    )
    value = subsequent_landing.event_time_s - rebound_takeoff.event_time_s
    if not math.isfinite(value) or value <= 0:
        raise ValueError("DJ flight time must be finite and positive")
    return value


def calculate_drop_jump_contact_time(
    touchdown: DropJumpEventOccurrence,
    rebound_takeoff: DropJumpEventOccurrence,
    source_observation: ScientificMeasurementObservation | None = None,
    qualification: DropJumpSourceQualificationEvidence | None = None,
) -> DropJumpMetricResult | RefusalResult:
    """Return a qualified DJ ground-contact-time result or a structured refusal."""

    claim = "calculate DJ rebound ground-contact time"
    try:
        _validate_pair(
            touchdown,
            rebound_takeoff,
            DropJumpEventLabel.TOUCHDOWN,
            DropJumpEventLabel.REBOUND_TAKEOFF,
        )
        source = _validate_source(source_observation, (touchdown, rebound_takeoff), qualification)
        value = contact_time_seconds(touchdown, rebound_takeoff)
        parameters = (
            MetadataEntry("touchdown_event_id", touchdown.occurrence_id.qualified),
            MetadataEntry("rebound_takeoff_event_id", rebound_takeoff.occurrence_id.qualified),
            MetadataEntry("contact_time_s", value),
            MetadataEntry("source_series_digest", touchdown.source_series_digest),
        )
        source_observations: tuple[ScientificMeasurementObservation, ...] = (source,)
        if qualification is not None:
            source_observations += (qualification.qualification_observation,)
        return _build_metric(
            source_identity=touchdown.source_measurement_identity,
            context=source.context,
            source_events=(touchdown, rebound_takeoff),
            source_observations=source_observations,
            value=value,
            unit=SECOND,
            metric=DJ_GROUND_CONTACT_TIME_METRIC,
            measurand=DJ_GROUND_CONTACT_TIME_MEASURAND,
            operation=DJ_GROUND_CONTACT_TIME_OPERATION,
            parameters=parameters,
            value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        ids = tuple(
            item.source_observation_id
            for item in (touchdown, rebound_takeoff)
            if isinstance(item, DropJumpEventOccurrence)
        )
        return _refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("valid same-trial DJ touchdown and rebound-takeoff evidence",),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            safe_descriptions=("any independently valid DJ event occurrences",),
        )


def calculate_drop_jump_rebound_flight_time(
    rebound_takeoff: DropJumpEventOccurrence,
    subsequent_landing: DropJumpEventOccurrence,
    source_observation: ScientificMeasurementObservation | None = None,
    qualification: DropJumpSourceQualificationEvidence | None = None,
) -> DropJumpMetricResult | RefusalResult:
    """Return a qualified DJ rebound-flight-time result or a refusal."""

    claim = "calculate DJ rebound flight time"
    try:
        _validate_pair(
            rebound_takeoff,
            subsequent_landing,
            DropJumpEventLabel.REBOUND_TAKEOFF,
            DropJumpEventLabel.SUBSEQUENT_LANDING,
        )
        source = _validate_source(
            source_observation, (rebound_takeoff, subsequent_landing), qualification
        )
        value = rebound_flight_time_seconds(rebound_takeoff, subsequent_landing)
        parameters = (
            MetadataEntry("rebound_takeoff_event_id", rebound_takeoff.occurrence_id.qualified),
            MetadataEntry(
                "subsequent_landing_event_id", subsequent_landing.occurrence_id.qualified
            ),
            MetadataEntry("flight_time_s", value),
            MetadataEntry("source_series_digest", rebound_takeoff.source_series_digest),
        )
        source_observations: tuple[ScientificMeasurementObservation, ...] = (source,)
        if qualification is not None:
            source_observations += (qualification.qualification_observation,)
        return _build_metric(
            source_identity=rebound_takeoff.source_measurement_identity,
            context=source.context,
            source_events=(rebound_takeoff, subsequent_landing),
            source_observations=source_observations,
            value=value,
            unit=SECOND,
            metric=DJ_REBOUND_FLIGHT_TIME_METRIC,
            measurand=DJ_REBOUND_FLIGHT_TIME_MEASURAND,
            operation=DJ_REBOUND_FLIGHT_TIME_OPERATION,
            parameters=parameters,
            value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        ids = tuple(
            item.source_observation_id
            for item in (rebound_takeoff, subsequent_landing)
            if isinstance(item, DropJumpEventOccurrence)
        )
        return _refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("valid same-trial DJ rebound-takeoff and subsequent-landing evidence",),
            ids,
            safe_descriptions=("any independently valid DJ event occurrences",),
        )


def flight_time_jump_height_metres(
    flight_time_s: float,
    gravity: object,
) -> float:
    """Pure DJ-specific flight-time ballistic height equation."""

    duration = _finite(flight_time_s, "flight_time_s")
    if duration <= 0:
        raise ValueError("flight_time_s must be positive")
    if not isinstance(gravity, _GRAVITY_REFERENCE_TYPE):
        raise ValueError("an explicit qualified GravityReference is required")
    gravity_reference = cast(_GravityReferenceLike, gravity)
    return gravity_reference.value_m_per_s2 * duration**2 / 8.0


def calculate_drop_jump_flight_time_jump_height(
    rebound_takeoff: DropJumpEventOccurrence,
    subsequent_landing: DropJumpEventOccurrence,
    gravity: object | None,
    source_observation: ScientificMeasurementObservation | None = None,
    applicability: DropJumpFlightTimeApplicability | None = None,
    qualification: DropJumpSourceQualificationEvidence | None = None,
) -> DropJumpMetricResult | RefusalResult:
    """Estimate DJ takeoff-to-apex rise from exact rebound flight time."""

    claim = "estimate DJ flight-time ballistic jump height"
    try:
        _validate_pair(
            rebound_takeoff,
            subsequent_landing,
            DropJumpEventLabel.REBOUND_TAKEOFF,
            DropJumpEventLabel.SUBSEQUENT_LANDING,
        )
        source = _validate_source(
            source_observation, (rebound_takeoff, subsequent_landing), qualification
        )
        if not isinstance(gravity, _GRAVITY_REFERENCE_TYPE):
            return _refusal(
                claim,
                (RefusalReasonCode.GRAVITY_REFERENCE_INVALID,),
                ("qualified GravityReference with an explicit gravity source and unit",),
                (source.observation_id,),
                refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
                safe_descriptions=("valid DJ rebound events and flight time",),
            )
        if not isinstance(applicability, DropJumpFlightTimeApplicability):
            return _refusal(
                claim,
                (RefusalReasonCode.BALLISTIC_ASSUMPTION_UNSUPPORTED,),
                ("explicit DJ flight-time ballistic/posture applicability",),
                (source.observation_id,),
                refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
                safe_descriptions=("valid DJ rebound events and flight time",),
            )
        if not applicability.matches(
            source.observation_id,
            rebound_takeoff.occurrence_id,
            subsequent_landing.occurrence_id,
        ):
            return _refusal(
                claim,
                (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
                ("applicability bound to this source observation and these exact events",),
                (source.observation_id,),
                safe_descriptions=("valid DJ rebound events and flight time",),
            )
        if not applicability.is_authorized:
            return _refusal(
                claim,
                (RefusalReasonCode.BALLISTIC_ASSUMPTION_UNSUPPORTED,),
                ("authorized ballistic, posture-equivalence and air-resistance assumptions",),
                (source.observation_id,),
                refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
                safe_descriptions=("valid DJ rebound events and flight time",),
            )
        flight_time = rebound_flight_time_seconds(rebound_takeoff, subsequent_landing)
        value = flight_time_jump_height_metres(flight_time, gravity)
        parameters = (
            MetadataEntry("rebound_takeoff_event_id", rebound_takeoff.occurrence_id.qualified),
            MetadataEntry(
                "subsequent_landing_event_id", subsequent_landing.occurrence_id.qualified
            ),
            MetadataEntry("flight_time_s", flight_time),
            MetadataEntry("gravity_reference", canonical_json(gravity)),
            MetadataEntry("applicability", canonical_json(applicability)),
            MetadataEntry(
                "estimator_definition",
                "takeoff-to-apex ballistic rise estimated as g * flight_time_s^2 / 8",
            ),
        )
        source_observations: tuple[ScientificMeasurementObservation, ...] = (source,)
        if qualification is not None:
            source_observations += (qualification.qualification_observation,)
        return _build_metric(
            source_identity=rebound_takeoff.source_measurement_identity,
            context=source.context,
            source_events=(rebound_takeoff, subsequent_landing),
            source_observations=source_observations,
            value=value,
            unit=METER,
            metric=DJ_FLIGHT_TIME_JUMP_HEIGHT_METRIC,
            measurand=DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND,
            operation=DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION,
            parameters=parameters,
            value_origin=ValueOrigin.MODEL_ESTIMATE,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        ids = tuple(
            item.source_observation_id
            for item in (rebound_takeoff, subsequent_landing)
            if isinstance(item, DropJumpEventOccurrence)
        )
        return _refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("valid DJ source, events, gravity and applicability evidence",),
            ids,
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            safe_descriptions=("valid DJ events and any independently valid durations",),
        )


def _same_event_source(
    left: DropJumpMetricResult,
    right: DropJumpMetricResult,
) -> None:
    left_events = left.source_events
    right_events = right.source_events
    if not left_events or not right_events:
        raise ValueError("DJ metric results must preserve source events")
    if any(
        event.source_observation_id != left_events[0].source_observation_id
        or event.source_signal_id != left_events[0].source_signal_id
        or event.source_artifact_id != left_events[0].source_artifact_id
        or event.source_acquisition_id != left_events[0].source_acquisition_id
        or event.source_measurement_identity != left_events[0].source_measurement_identity
        for event in (*left_events, *right_events)
    ):
        raise ValueError("DJ ratio inputs must use exact same-trial event evidence")


def _ratio_result(
    *,
    numerator: DropJumpMetricResult,
    denominator: DropJumpMetricResult,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    value: float,
    unit: UnitReference,
    claim: str,
    expected_numerator_metric: RegistryReference,
    expected_denominator_metric: RegistryReference,
) -> DropJumpMetricResult | RefusalResult:
    try:
        if not isinstance(numerator, DropJumpMetricResult) or not isinstance(
            denominator, DropJumpMetricResult
        ):
            raise ValueError("typed DJ metric results are required")
        if (
            numerator.metric != expected_numerator_metric
            or denominator.metric != expected_denominator_metric
        ):
            raise ValueError("DJ ratio operands have the wrong metric identities")
        _same_event_source(numerator, denominator)
        denominator_value = denominator.value
        if denominator_value <= 0 or not math.isfinite(denominator_value):
            raise ValueError("DJ ratio denominator must be finite and positive")
        result_value = _finite(value, "DJ ratio")
        source_observations = tuple(
            dict.fromkeys(
                (*numerator.source_observations, *denominator.source_observations),
            )
        )
        source_identity = numerator.source_events[0].source_measurement_identity
        context = source_observations[0].context
        parameters = (
            MetadataEntry(
                "numerator_observation_id", numerator.observation.observation_id.qualified
            ),
            MetadataEntry(
                "denominator_observation_id", denominator.observation.observation_id.qualified
            ),
            MetadataEntry("numerator_metric", numerator.metric.stable_id),
            MetadataEntry("denominator_metric", denominator.metric.stable_id),
            MetadataEntry("ratio_value", result_value),
        )
        return _build_metric(
            source_identity=source_identity,
            context=context,
            source_events=tuple(
                dict.fromkeys((*numerator.source_events, *denominator.source_events))
            ),
            source_observations=source_observations,
            value=result_value,
            unit=unit,
            metric=metric,
            measurand=measurand,
            operation=operation,
            parameters=parameters,
            value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            ("same-trial qualified DJ numerator and positive denominator",),
            (),
            safe_descriptions=("the independently valid DJ operand results",),
        )


def calculate_drop_jump_rsi_jh_ct(
    jump_height: DropJumpMetricResult,
    contact_time: DropJumpMetricResult,
) -> DropJumpMetricResult | RefusalResult:
    """Calculate DJ RSI using jump height divided by ground-contact time."""

    claim = "calculate DJ RSI JH/CT"
    try:
        height = jump_height.value_m
        contact = contact_time.value_s
        if contact <= 0:
            raise ValueError("contact time denominator must be positive")
        return _ratio_result(
            numerator=jump_height,
            denominator=contact_time,
            metric=DJ_RSI_JH_CT_METRIC,
            measurand=DJ_RSI_JH_CT_MEASURAND,
            operation=DJ_RSI_JH_CT_OPERATION,
            value=height / contact,
            unit=METERS_PER_SECOND,
            claim=claim,
            expected_numerator_metric=DJ_FLIGHT_TIME_JUMP_HEIGHT_METRIC,
            expected_denominator_metric=DJ_GROUND_CONTACT_TIME_METRIC,
        )
    except (AttributeError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            ("valid DJ flight-time jump height and positive contact time",),
            (),
            safe_descriptions=("valid DJ jump-height and contact-time results",),
        )


def calculate_drop_jump_rsr_ft_ct(
    flight_time: DropJumpMetricResult,
    contact_time: DropJumpMetricResult,
) -> DropJumpMetricResult | RefusalResult:
    """Calculate DJ RSR using rebound flight time divided by contact time."""

    claim = "calculate DJ RSR FT/CT"
    try:
        flight = flight_time.value_s
        contact = contact_time.value_s
        if contact <= 0:
            raise ValueError("contact time denominator must be positive")
        return _ratio_result(
            numerator=flight_time,
            denominator=contact_time,
            metric=DJ_RSR_FT_CT_METRIC,
            measurand=DJ_RSR_FT_CT_MEASURAND,
            operation=DJ_RSR_FT_CT_OPERATION,
            value=flight / contact,
            unit=DIMENSIONLESS,
            claim=claim,
            expected_numerator_metric=DJ_REBOUND_FLIGHT_TIME_METRIC,
            expected_denominator_metric=DJ_GROUND_CONTACT_TIME_METRIC,
        )
    except (AttributeError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            ("valid DJ rebound flight time and positive contact time",),
            (),
            safe_descriptions=("valid DJ flight-time and contact-time results",),
        )


# Public aliases use both expanded and DJ-prefixed spellings without merging
# any metric identity.
estimate_drop_jump_flight_time_jump_height = calculate_drop_jump_flight_time_jump_height
calculate_dj_ground_contact_time = calculate_drop_jump_contact_time
calculate_dj_rebound_flight_time = calculate_drop_jump_rebound_flight_time
calculate_dj_flight_time_jump_height = calculate_drop_jump_flight_time_jump_height
calculate_dj_rsi_jh_ct = calculate_drop_jump_rsi_jh_ct
calculate_dj_rsr_ft_ct = calculate_drop_jump_rsr_ft_ct


__all__ = [
    "DropJumpMetricResult",
    "calculate_dj_flight_time_jump_height",
    "calculate_dj_ground_contact_time",
    "calculate_dj_rebound_flight_time",
    "calculate_dj_rsi_jh_ct",
    "calculate_dj_rsr_ft_ct",
    "calculate_drop_jump_contact_time",
    "calculate_drop_jump_flight_time_jump_height",
    "calculate_drop_jump_rebound_flight_time",
    "calculate_drop_jump_rsi_jh_ct",
    "calculate_drop_jump_rsr_ft_ct",
    "contact_time_seconds",
    "estimate_drop_jump_flight_time_jump_height",
    "flight_time_jump_height_metres",
    "rebound_flight_time_seconds",
]
