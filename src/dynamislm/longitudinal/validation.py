"""Public fail-closed validators for RES-62 boundary objects."""

from __future__ import annotations

from dynamislm.longitudinal.lineage import (
    validate_complete_multi_source_provenance_graph,
    validate_multi_source_provenance_graph,
)
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    LongitudinalSourceManifestResult,
    MultiSourceAnalysisInput,
    MultiSourceProcessingRun,
    MultiSourceProvenanceGraph,
    SourceArtifactQualificationBinding,
)


def validate_source_artifact_qualification_binding(
    binding: SourceArtifactQualificationBinding,
) -> None:
    if not isinstance(binding, SourceArtifactQualificationBinding):
        raise ValueError("binding must be a SourceArtifactQualificationBinding")


def validate_longitudinal_observation_entry(entry: LongitudinalObservationEntry) -> None:
    if not isinstance(entry, LongitudinalObservationEntry):
        raise ValueError("entry must be a LongitudinalObservationEntry")


def validate_longitudinal_record(record: LongitudinalAthletePerformanceRecord) -> None:
    if not isinstance(record, LongitudinalAthletePerformanceRecord):
        raise ValueError("record must be a LongitudinalAthletePerformanceRecord")


def validate_multi_source_analysis_input(analysis_input: MultiSourceAnalysisInput) -> None:
    if not isinstance(analysis_input, MultiSourceAnalysisInput):
        raise ValueError("analysis_input must be a MultiSourceAnalysisInput")


def validate_multi_source_processing_run(processing_run: MultiSourceProcessingRun) -> None:
    if not isinstance(processing_run, MultiSourceProcessingRun):
        raise ValueError("processing_run must be a MultiSourceProcessingRun")


def validate_longitudinal_source_manifest_result(
    result: LongitudinalSourceManifestResult,
) -> None:
    if not isinstance(result, LongitudinalSourceManifestResult):
        raise ValueError("result must be a LongitudinalSourceManifestResult")


def validate_provenance_graph(graph: MultiSourceProvenanceGraph) -> None:
    if not isinstance(graph, MultiSourceProvenanceGraph):
        raise ValueError("graph must be a MultiSourceProvenanceGraph")


__all__ = [
    "validate_complete_multi_source_provenance_graph",
    "validate_longitudinal_observation_entry",
    "validate_longitudinal_record",
    "validate_longitudinal_source_manifest_result",
    "validate_multi_source_analysis_input",
    "validate_multi_source_processing_run",
    "validate_multi_source_provenance_graph",
    "validate_provenance_graph",
    "validate_source_artifact_qualification_binding",
]
