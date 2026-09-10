"""The composite scientific observation and append-only derivation constructor."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
)
from dynamislm.measurement.result import MeasurementResult
from dynamislm.provenance.models import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.serialization import register_serializable_type


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Observation-instance context, separate from scientific measurement identity."""

    context_id: InstanceIdentifier
    athlete_id: InstanceIdentifier
    session_id: InstanceIdentifier
    test_instance_id: InstanceIdentifier
    trial_id: InstanceIdentifier | None
    observed_at: datetime_module.datetime
    population_context: str
    environment: tuple[MetadataEntry, ...] = ()
    context_metadata: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.context_id, InstanceIdentifier, "context_id")
        if self.context_id.instance_type != "context":
            raise ValueError("context_id must identify a context")
        _require_instance(self.athlete_id, InstanceIdentifier, "athlete_id")
        if self.athlete_id.instance_type != "athlete":
            raise ValueError("athlete_id must identify an athlete")
        _require_instance(self.session_id, InstanceIdentifier, "session_id")
        if self.session_id.instance_type != "session":
            raise ValueError("session_id must identify a session")
        _require_instance(self.test_instance_id, InstanceIdentifier, "test_instance_id")
        if self.test_instance_id.instance_type != "test-instance":
            raise ValueError("test_instance_id must identify a test-instance")
        _require_optional_instance(self.trial_id, InstanceIdentifier, "trial_id")
        if self.trial_id is not None and self.trial_id.instance_type != "trial":
            raise ValueError("trial_id must identify a trial")
        if not isinstance(self.observed_at, datetime_module.datetime):
            raise ValueError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include an explicit timezone")
        _require_text(self.population_context, "population_context")
        _require_tuple_items(self.environment, MetadataEntry, "environment")
        _require_tuple_items(self.context_metadata, MetadataEntry, "context_metadata")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScientificMeasurementObservation:
    """Context + identity + result + provenance, with each concern independently typed."""

    observation_id: InstanceIdentifier
    context: ObservationContext
    identity: MeasurementIdentity
    result: MeasurementResult
    provenance: Provenance

    def __post_init__(self) -> None:
        _require_instance(self.observation_id, InstanceIdentifier, "observation_id")
        if self.observation_id.instance_type != "observation":
            raise ValueError(
                "scientific measurement observation ID must have instance_type observation"
            )
        _require_instance(self.context, ObservationContext, "context")
        _require_instance(self.identity, MeasurementIdentity, "identity")
        _require_instance(self.result, MeasurementResult, "result")
        _require_instance(self.provenance, Provenance, "provenance")


def create_derived_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: MeasurementIdentity,
    result: MeasurementResult,
    source_artifact: SourceArtifact,
    acquisition: AcquisitionRecord,
    processing_run: ProcessingRun,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Create a new immutable derived observation for one processing run.

    The constructor intentionally has no update operation: a changed method or
    parameter set must be represented by another processing run and observation.
    """

    if observation_id.instance_type != "observation":
        raise ValueError("derived observation ID must have instance_type observation")
    if processing_run.output_entity_id != observation_id:
        raise ValueError("processing run output entity must equal the new observation ID")
    if source_artifact.artifact_id not in processing_run.source_artifact_ids:
        raise ValueError("processing run must reference the source artifact")
    if acquisition.source_artifact_id != source_artifact.artifact_id:
        raise ValueError("acquisition must reference the source artifact")
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", observation_id.value),
        source_artifacts=(source_artifact,),
        acquisitions=(acquisition,),
        processing_runs=(processing_run,),
        lineage_edges=(
            LineageEdge(
                source_artifact.artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                LineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                processing_run.processing_run_id.qualified,
                LineageRelation.PROCESSED_AS,
            ),
            LineageEdge(
                processing_run.processing_run_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
        evidence_references=evidence_references,
        recorded_at=recorded_at,
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        provenance=provenance,
    )
