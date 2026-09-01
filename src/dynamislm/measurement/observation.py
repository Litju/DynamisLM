"""The composite scientific observation and append-only derivation constructor."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    require_tuple,
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


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


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
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include an explicit timezone")
        _require_text(self.population_context, "population_context")
        require_tuple(self.environment, "environment")
        require_tuple(self.context_metadata, "context_metadata")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScientificMeasurementObservation:
    """Context + identity + result + provenance, with each concern independently typed."""

    observation_id: InstanceIdentifier
    context: ObservationContext
    identity: MeasurementIdentity
    result: MeasurementResult
    provenance: Provenance


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

    if processing_run.output_observation_id != observation_id:
        raise ValueError("processing run output must equal the new observation ID")
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
