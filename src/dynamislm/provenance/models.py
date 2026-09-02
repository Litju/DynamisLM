"""Source, acquisition, processing, and lineage records."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    SamplingCharacteristics,
    require_tuple,
)
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class LineageRelation(StrEnum):
    DERIVED_FROM = "DERIVED_FROM"
    ACQUIRED_AS = "ACQUIRED_AS"
    PROCESSED_AS = "PROCESSED_AS"
    PRODUCED = "PRODUCED"
    SUPPORTED_BY = "SUPPORTED_BY"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceArtifact:
    artifact_id: InstanceIdentifier
    content_digest: str
    media_type: str
    immutable: bool = True

    def __post_init__(self) -> None:
        _require_text(self.content_digest, "content_digest")
        _require_text(self.media_type, "media_type")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    acquisition_id: InstanceIdentifier
    device: RegistryReference
    source_artifact_id: InstanceIdentifier
    sensor_channel: str | None = None
    sampling: SamplingCharacteristics | None = None
    calibration_reference: RegistryReference | None = None
    hardware_firmware: RegistryReference | None = None

    def __post_init__(self) -> None:
        if self.sensor_channel is not None:
            _require_text(self.sensor_channel, "sensor_channel")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProcessingRun:
    processing_run_id: InstanceIdentifier
    source_artifact_ids: tuple[InstanceIdentifier, ...]
    method: RegistryReference
    parameters: tuple[MetadataEntry, ...]
    software_version: str
    output_entity_id: InstanceIdentifier

    def __post_init__(self) -> None:
        if not self.source_artifact_ids:
            raise ValueError("processing run must reference at least one source artifact")
        require_tuple(self.source_artifact_ids, "source_artifact_ids")
        require_tuple(self.parameters, "parameters")
        _require_text(self.software_version, "software_version")
        if not isinstance(self.output_entity_id, InstanceIdentifier):
            raise ValueError("output_entity_id must be an InstanceIdentifier")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference: RegistryReference
    applicability_note: str | None = None

    def __post_init__(self) -> None:
        if self.applicability_note is not None:
            _require_text(self.applicability_note, "applicability_note")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LineageEdge:
    from_id: str
    to_id: str
    relation: LineageRelation

    def __post_init__(self) -> None:
        _require_text(self.from_id, "from_id")
        _require_text(self.to_id, "to_id")
        if self.from_id == self.to_id:
            raise ValueError("lineage edge cannot point to itself")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class Provenance:
    """Immutable computational/data lineage, distinct from metrological traceability."""

    provenance_id: InstanceIdentifier
    source_artifacts: tuple[SourceArtifact, ...]
    acquisitions: tuple[AcquisitionRecord, ...]
    processing_runs: tuple[ProcessingRun, ...]
    lineage_edges: tuple[LineageEdge, ...]
    evidence_references: tuple[EvidenceReference, ...] = ()
    metrological_traceability: tuple[RegistryReference, ...] = ()
    recorded_at: datetime_module.datetime | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_artifacts", self.source_artifacts),
            ("acquisitions", self.acquisitions),
            ("processing_runs", self.processing_runs),
            ("lineage_edges", self.lineage_edges),
            ("evidence_references", self.evidence_references),
            ("metrological_traceability", self.metrological_traceability),
        ):
            require_tuple(value, field_name)
        if self.recorded_at is not None and (
            self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None
        ):
            raise ValueError("recorded_at must include an explicit timezone")
        artifact_ids = {artifact.artifact_id.qualified for artifact in self.source_artifacts}
        for acquisition in self.acquisitions:
            if acquisition.source_artifact_id.qualified not in artifact_ids:
                raise ValueError("acquisition references an artifact absent from provenance")
        processing_ids = {run.processing_run_id.qualified for run in self.processing_runs}
        for edge in self.lineage_edges:
            if edge.relation is LineageRelation.PROCESSED_AS and edge.to_id not in processing_ids:
                raise ValueError("processed-as lineage edge must target a processing run")
        for run in self.processing_runs:
            output_edges = tuple(
                edge
                for edge in self.lineage_edges
                if edge.from_id == run.processing_run_id.qualified
                and edge.to_id == run.output_entity_id.qualified
                and edge.relation is LineageRelation.PRODUCED
            )
            if len(output_edges) != 1:
                raise ValueError(
                    "processing run must have exactly one PRODUCED edge to its output entity"
                )
