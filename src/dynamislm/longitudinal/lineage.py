"""Deterministic construction and validation of the RES-62 provenance DAG."""

from __future__ import annotations

from dynamislm.longitudinal.models import (
    LongitudinalLineageEdge,
    LongitudinalLineageNode,
    LongitudinalLineageNodeKind,
    LongitudinalLineageRelation,
    MultiSourceAnalysisInput,
    MultiSourceProcessingRun,
    MultiSourceProvenanceGraph,
    _structural_result_content_hash,
)
from dynamislm.measurement.identity import RegistryReference
from dynamislm.provenance.models import LineageRelation as SourceLineageRelation
from dynamislm.provenance.models import Provenance
from dynamislm.serialization import canonical_hash


class _NodeIndex:
    """Small collision-checking node accumulator for one complete graph build."""

    def __init__(self) -> None:
        self.nodes: dict[str, LongitudinalLineageNode] = {}

    def add(
        self,
        node_id: str,
        kind: LongitudinalLineageNodeKind,
        content: object,
        *,
        content_hash: str | None = None,
    ) -> None:
        node = LongitudinalLineageNode(
            node_id=node_id,
            kind=kind,
            content_hash=content_hash or canonical_hash(content),
        )
        existing = self.nodes.get(node_id)
        if existing is not None:
            if existing.kind is not node.kind or existing.content_hash != node.content_hash:
                raise ValueError(
                    f"lineage node ID {node_id!r} has conflicting kind or canonical hash"
                )
            return
        self.nodes[node_id] = node


class _EdgeIndex:
    """Exact-edge accumulator; relation differences remain scientifically visible."""

    def __init__(self) -> None:
        self.edges: dict[tuple[str, str, str], LongitudinalLineageEdge] = {}

    def add(
        self,
        from_id: str,
        to_id: str,
        relation: LongitudinalLineageRelation,
    ) -> None:
        edge = LongitudinalLineageEdge(from_id=from_id, to_id=to_id, relation=relation)
        self.edges[(from_id, to_id, relation.value)] = edge


def _registry_references_for_source_provenance(
    provenance: Provenance,
) -> tuple[RegistryReference, ...]:
    """Collect registry references that can legally appear in source edge endpoints."""

    references: list[RegistryReference] = []
    for evidence in provenance.evidence_references:
        references.append(evidence.reference)
    for reference in provenance.metrological_traceability:
        references.append(reference)
    for acquisition in provenance.acquisitions:
        references.append(acquisition.device)
        if acquisition.calibration_reference is not None:
            references.append(acquisition.calibration_reference)
        if acquisition.hardware_firmware is not None:
            references.append(acquisition.hardware_firmware)
    for run in provenance.processing_runs:
        references.append(run.method)
    unique: list[RegistryReference] = []
    for reference in references:
        if reference not in unique:
            unique.append(reference)
    return tuple(unique)


def _add_source_provenance(
    nodes: _NodeIndex,
    edges: _EdgeIndex,
    observation_id: str,
    provenance: Provenance,
    selected_observation_ids: set[str],
) -> None:
    """Union one unchanged Provenance while rejecting unrepresented dependencies."""

    artifacts = provenance.source_artifacts
    acquisitions = provenance.acquisitions
    processing_runs = provenance.processing_runs
    source_edges = provenance.lineage_edges
    artifact_ids = {artifact.artifact_id.qualified for artifact in artifacts}
    acquisition_ids = {acquisition.acquisition_id.qualified for acquisition in acquisitions}
    processing_ids = {run.processing_run_id.qualified for run in processing_runs}
    evidence_references = _registry_references_for_source_provenance(
        provenance,
    )
    registry_ids = {reference.stable_id for reference in evidence_references}

    for artifact in artifacts:
        nodes.add(
            artifact.artifact_id.qualified,
            LongitudinalLineageNodeKind.SOURCE_ARTIFACT,
            artifact,
        )
    for acquisition in acquisitions:
        if acquisition.source_artifact_id.qualified not in artifact_ids:
            raise ValueError("acquisition references an artifact absent from source provenance")
        nodes.add(
            acquisition.acquisition_id.qualified,
            LongitudinalLineageNodeKind.ACQUISITION_RECORD,
            acquisition,
        )
    for run in processing_runs:
        if any(item.qualified not in artifact_ids for item in run.source_artifact_ids):
            raise ValueError("source processing run references an artifact absent from provenance")
        nodes.add(
            run.processing_run_id.qualified,
            LongitudinalLineageNodeKind.SOURCE_PROCESSING_RUN,
            run,
        )
    for reference in evidence_references:
        nodes.add(
            reference.stable_id,
            LongitudinalLineageNodeKind.REGISTRY_REFERENCE,
            reference,
        )

    known_ids = {
        *artifact_ids,
        *acquisition_ids,
        *processing_ids,
        observation_id,
        *selected_observation_ids,
        *registry_ids,
    }
    for source_edge in source_edges:
        if source_edge.from_id not in known_ids or source_edge.to_id not in known_ids:
            raise ValueError(
                "source provenance contains a lineage edge endpoint without a represented "
                "dependency"
            )
        try:
            relation = LongitudinalLineageRelation(source_edge.relation.value)
        except ValueError as exc:
            raise ValueError("source provenance contains an unsupported lineage relation") from exc
        edges.add(source_edge.from_id, source_edge.to_id, relation)

    # Existing Provenance validates a processing run's produced edge.  RES-62
    # additionally requires enough source edges to make each listed dependency
    # actually reach the selected observation rather than merely appear in a
    # metadata array.
    for acquisition in acquisitions:
        acquired_edge = (
            acquisition.source_artifact_id.qualified,
            acquisition.acquisition_id.qualified,
            SourceLineageRelation.ACQUIRED_AS.value,
        )
        if not any(
            (edge.from_id, edge.to_id, edge.relation.value) == acquired_edge
            for edge in source_edges
        ):
            raise ValueError("source provenance is missing an artifact-to-acquisition dependency")

    source_adjacency: dict[str, list[str]] = {}
    for edge in source_edges:
        source_adjacency.setdefault(edge.from_id, []).append(edge.to_id)

    def reaches(start: str, target: str) -> bool:
        pending = [start]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(source_adjacency.get(current, ()))
        return False

    for dependency_id in (*artifact_ids, *acquisition_ids, *processing_ids):
        if not reaches(dependency_id, observation_id):
            raise ValueError(
                f"source provenance dependency {dependency_id!r} does not reach the observation"
            )


def build_multi_source_provenance_graph(
    analysis_input: MultiSourceAnalysisInput,
    processing_run: MultiSourceProcessingRun,
) -> MultiSourceProvenanceGraph:
    """Build the complete deterministic union of source and RES-62 lineage."""

    if not isinstance(analysis_input, MultiSourceAnalysisInput):
        raise ValueError("analysis_input must be a MultiSourceAnalysisInput")
    if not isinstance(processing_run, MultiSourceProcessingRun):
        raise ValueError("processing_run must be a MultiSourceProcessingRun")
    if processing_run.analysis_input_id != analysis_input.analysis_input_id:
        raise ValueError("processing run must reference the supplied analysis input")
    if processing_run.analysis_input_hash != analysis_input.input_hash:
        raise ValueError("processing run input hash must match the supplied analysis input")
    if tuple(sorted(analysis_input.source_observation_ids, key=lambda item: item.qualified)) != (
        processing_run.source_observation_ids
    ):
        raise ValueError("processing run source observations must match the analysis input")

    nodes = _NodeIndex()
    edges = _EdgeIndex()
    selected_observation_ids = {
        observation_id.qualified for observation_id in analysis_input.source_observation_ids
    }

    nodes.add(
        analysis_input.analysis_input_id.qualified,
        LongitudinalLineageNodeKind.ANALYSIS_INPUT,
        analysis_input,
    )
    for entry in analysis_input.entries:
        observation = entry.observation
        observation_id = observation.observation_id.qualified
        nodes.add(
            observation_id,
            LongitudinalLineageNodeKind.SOURCE_OBSERVATION,
            observation,
        )
        _add_source_provenance(
            nodes,
            edges,
            observation_id,
            observation.provenance,
            selected_observation_ids,
        )
        nodes.add(
            entry.football_context.context_id.qualified,
            LongitudinalLineageNodeKind.FOOTBALL_WORLD_CONTEXT,
            entry.football_context,
        )
        nodes.add(
            entry.canonical_entry_id.qualified,
            LongitudinalLineageNodeKind.LONGITUDINAL_ENTRY,
            entry,
        )
        edges.add(
            observation_id,
            entry.football_context.context_id.qualified,
            LongitudinalLineageRelation.CONTEXTUALIZED_BY,
        )
        edges.add(
            observation_id,
            entry.canonical_entry_id.qualified,
            LongitudinalLineageRelation.SELECTED_AS,
        )
        edges.add(
            entry.football_context.context_id.qualified,
            entry.canonical_entry_id.qualified,
            LongitudinalLineageRelation.CONTEXTUALIZED_BY,
        )
        for binding in entry.source_qualification_bindings:
            nodes.add(
                binding.binding_id.qualified,
                LongitudinalLineageNodeKind.SOURCE_QUALIFICATION,
                binding,
            )
            for artifact_id in binding.source_artifact_ids:
                edges.add(
                    artifact_id.qualified,
                    binding.binding_id.qualified,
                    LongitudinalLineageRelation.QUALIFIED_BY,
                )
            edges.add(
                binding.binding_id.qualified,
                entry.canonical_entry_id.qualified,
                LongitudinalLineageRelation.QUALIFIED_BY,
            )
        edges.add(
            entry.canonical_entry_id.qualified,
            analysis_input.analysis_input_id.qualified,
            LongitudinalLineageRelation.SELECTED_AS,
        )

    nodes.add(
        processing_run.run_id.qualified,
        LongitudinalLineageNodeKind.MULTI_SOURCE_PROCESSING_RUN,
        processing_run,
    )
    edges.add(
        analysis_input.input_id.qualified,
        processing_run.run_id.qualified,
        LongitudinalLineageRelation.ANALYZED_AS,
    )

    selected_ids = analysis_input.source_observation_ids
    selected_hashes = analysis_input.selected_entry_hashes
    manifest_hash = canonical_hash(
        {
            "analysis_input_id": analysis_input.input_id,
            "scope": analysis_input.scope,
            "selected_observation_ids": selected_ids,
            "selected_entry_hashes": selected_hashes,
        }
    )
    result_node_hash = _structural_result_content_hash(
        processing_run.output_id,
        analysis_input,
        processing_run,
        selected_ids,
        selected_hashes,
        len(selected_ids),
        manifest_hash,
    )
    nodes.add(
        processing_run.output_id.qualified,
        LongitudinalLineageNodeKind.DERIVED_RESULT,
        processing_run.output_id,
        content_hash=result_node_hash,
    )
    edges.add(
        processing_run.run_id.qualified,
        processing_run.output_id.qualified,
        LongitudinalLineageRelation.PRODUCED,
    )

    return MultiSourceProvenanceGraph(
        nodes=tuple(
            sorted(
                nodes.nodes.values(),
                key=lambda item: (item.kind.value, item.node_id, item.content_hash),
            )
        ),
        edges=tuple(
            sorted(
                edges.edges.values(),
                key=lambda item: (item.from_id, item.to_id, item.relation.value),
            )
        ),
    )


def validate_multi_source_provenance_graph(
    graph: MultiSourceProvenanceGraph,
    analysis_input: MultiSourceAnalysisInput,
    processing_run: MultiSourceProcessingRun,
) -> None:
    """Rebuild the expected graph and fail closed on any missing or extra content."""

    if not isinstance(graph, MultiSourceProvenanceGraph):
        raise ValueError("graph must be a MultiSourceProvenanceGraph")
    expected = build_multi_source_provenance_graph(analysis_input, processing_run)
    if graph != expected:
        raise ValueError("multi-source provenance graph does not match its embedded dependencies")


def graph_reaches(graph: MultiSourceProvenanceGraph, from_id: str, to_id: str) -> bool:
    """Return deterministic reachability for callers inspecting a validated graph."""

    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_id, []).append(edge.to_id)
    pending = [from_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == to_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return False


# Names used by the decision record and by callers that prefer an explicit
# "complete" qualifier all resolve to the same deterministic builder.
build_complete_multi_source_provenance_graph = build_multi_source_provenance_graph
validate_complete_multi_source_provenance_graph = validate_multi_source_provenance_graph


__all__ = [
    "build_complete_multi_source_provenance_graph",
    "build_multi_source_provenance_graph",
    "graph_reaches",
    "validate_complete_multi_source_provenance_graph",
    "validate_multi_source_provenance_graph",
]
