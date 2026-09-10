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
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
)
from dynamislm.serialization import register_serializable_type


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
        _require_instance(self.artifact_id, InstanceIdentifier, "artifact_id")
        if self.artifact_id.instance_type != "artifact":
            raise ValueError("artifact_id must identify an artifact")
        _require_text(self.content_digest, "content_digest")
        _require_text(self.media_type, "media_type")
        if not isinstance(self.immutable, bool):
            raise ValueError("immutable must be a boolean")


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
        _require_instance(self.acquisition_id, InstanceIdentifier, "acquisition_id")
        if self.acquisition_id.instance_type != "acquisition":
            raise ValueError("acquisition_id must identify an acquisition")
        _require_instance(self.device, RegistryReference, "device")
        _require_instance(self.source_artifact_id, InstanceIdentifier, "source_artifact_id")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("source_artifact_id must identify an artifact")
        if self.sensor_channel is not None:
            _require_text(self.sensor_channel, "sensor_channel")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(
            self.calibration_reference,
            RegistryReference,
            "calibration_reference",
        )
        _require_optional_instance(
            self.hardware_firmware,
            RegistryReference,
            "hardware_firmware",
        )


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
        _require_instance(self.processing_run_id, InstanceIdentifier, "processing_run_id")
        if self.processing_run_id.instance_type != "processing-run":
            raise ValueError("processing_run_id must identify a processing run")
        if not self.source_artifact_ids:
            raise ValueError("processing run must reference at least one source artifact")
        _require_tuple_items(self.source_artifact_ids, InstanceIdentifier, "source_artifact_ids")
        if any(item.instance_type != "artifact" for item in self.source_artifact_ids):
            raise ValueError("source_artifact_ids must identify artifacts")
        _require_instance(self.method, RegistryReference, "method")
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")
        _require_text(self.software_version, "software_version")
        _require_instance(self.output_entity_id, InstanceIdentifier, "output_entity_id")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference: RegistryReference
    applicability_note: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
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
        _require_enum(self.relation, LineageRelation, "relation")
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
        _require_instance(self.provenance_id, InstanceIdentifier, "provenance_id")
        if self.provenance_id.instance_type != "provenance":
            raise ValueError("provenance_id must identify provenance")
        _require_tuple_items(self.source_artifacts, SourceArtifact, "source_artifacts")
        _require_tuple_items(self.acquisitions, AcquisitionRecord, "acquisitions")
        _require_tuple_items(self.processing_runs, ProcessingRun, "processing_runs")
        _require_tuple_items(self.lineage_edges, LineageEdge, "lineage_edges")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        _require_tuple_items(
            self.metrological_traceability,
            RegistryReference,
            "metrological_traceability",
        )
        if self.recorded_at is not None and not isinstance(
            self.recorded_at,
            datetime_module.datetime,
        ):
            raise ValueError("recorded_at must be a datetime")
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
