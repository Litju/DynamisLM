"""Deterministic builders for RES-62 records, inputs, runs, and manifests."""

from __future__ import annotations

import datetime as datetime_module
from collections.abc import Iterable

from dynamislm.football.models import AthleteIdentity, FootballWorldContext
from dynamislm.longitudinal.lineage import build_multi_source_provenance_graph
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    LongitudinalRecordOrigin,
    LongitudinalSourceManifestResult,
    MultiSourceAnalysisInput,
    MultiSourceAnalysisScope,
    MultiSourceProcessingRun,
    SourceArtifactQualificationBinding,
    _manifest_hash,
)
from dynamislm.longitudinal.registry import RES62_MULTI_SOURCE_MANIFEST, RES62_SOFTWARE_VERSION
from dynamislm.measurement.identity import InstanceIdentifier, MetadataEntry, RegistryReference
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.population.models import CanonicalSourceDecision
from dynamislm.provenance.models import EvidenceReference


def _deduplicate_entries(
    entries: Iterable[LongitudinalObservationEntry],
) -> tuple[LongitudinalObservationEntry, ...]:
    """Collapse exact observation-ID/content duplicates and reject conflicts."""

    by_observation_id: dict[str, LongitudinalObservationEntry] = {}
    for entry in entries:
        if not isinstance(entry, LongitudinalObservationEntry):
            raise ValueError("entries must contain LongitudinalObservationEntry values")
        observation_key = entry.source_observation_id.qualified
        previous = by_observation_id.get(observation_key)
        if previous is None:
            by_observation_id[observation_key] = entry
            continue
        if previous.canonical_entry_hash != entry.canonical_entry_hash:
            raise ValueError(
                f"conflicting duplicate observation ID {observation_key!r} has different content"
            )
        # Exact duplicates are intentionally collapsed.  Different IDs are
        # never compared by values, labels, timestamps, or measurement identity.

    return tuple(
        sorted(
            by_observation_id.values(),
            key=lambda item: (
                item.observed_at.astimezone(datetime_module.UTC).isoformat(timespec="microseconds"),
                item.source_observation_id.qualified,
                item.canonical_entry_hash,
            ),
        )
    )


def build_longitudinal_observation_entry(
    observation: ScientificMeasurementObservation,
    football_context: FootballWorldContext,
    source_qualification_bindings: tuple[SourceArtifactQualificationBinding, ...],
) -> LongitudinalObservationEntry:
    """Wrap an existing observation without changing its identity or provenance."""

    return LongitudinalObservationEntry(
        observation=observation,
        football_context=football_context,
        source_qualification_bindings=source_qualification_bindings,
    )


build_contextualized_scientific_observation = build_longitudinal_observation_entry


def build_source_artifact_qualification_binding(
    canonical_source_decision: CanonicalSourceDecision,
    source_artifact_ids: tuple[InstanceIdentifier, ...],
    evidence_references: tuple[EvidenceReference, ...] = (),
) -> SourceArtifactQualificationBinding:
    """Create a binding with a content-derived stable binding ID."""

    if not isinstance(canonical_source_decision, CanonicalSourceDecision):
        raise ValueError("canonical_source_decision must be a CanonicalSourceDecision")
    if any(not isinstance(item, EvidenceReference) for item in evidence_references):
        raise ValueError("evidence_references must contain EvidenceReference values")
    return SourceArtifactQualificationBinding.from_decision(
        canonical_source_decision,
        source_artifact_ids,
        tuple(evidence_references),
    )


def build_longitudinal_record(
    athlete: AthleteIdentity,
    entries: Iterable[LongitudinalObservationEntry],
    origin: LongitudinalRecordOrigin,
) -> LongitudinalAthletePerformanceRecord:
    """Build one canonical immutable record snapshot for one athlete."""

    canonical_entries = _deduplicate_entries(entries)
    return LongitudinalAthletePerformanceRecord(
        origin=origin,
        athlete=athlete,
        entries=canonical_entries,
    )


def build_multi_source_analysis_input(
    athlete: AthleteIdentity,
    entries: Iterable[LongitudinalObservationEntry],
    scope: MultiSourceAnalysisScope,
) -> MultiSourceAnalysisInput:
    """Build a scope-checked, self-contained multi-source input snapshot."""

    canonical_entries = _deduplicate_entries(entries)
    return MultiSourceAnalysisInput(
        athlete=athlete,
        entries=canonical_entries,
        scope=scope,
    )


def build_multi_source_processing_run(
    analysis_input: MultiSourceAnalysisInput,
    *,
    method: RegistryReference = RES62_MULTI_SOURCE_MANIFEST,
    parameters: tuple[MetadataEntry, ...] = (),
    software_version: str = RES62_SOFTWARE_VERSION,
) -> MultiSourceProcessingRun:
    """Create an immutable run identity from input, method, parameters, and software."""

    if not isinstance(analysis_input, MultiSourceAnalysisInput):
        raise ValueError("analysis_input must be a MultiSourceAnalysisInput")
    return MultiSourceProcessingRun(
        analysis_input_id=analysis_input.input_id,
        analysis_input_hash=analysis_input.input_hash,
        source_observation_ids=tuple(
            sorted(analysis_input.source_observation_ids, key=lambda item: item.qualified)
        ),
        method=method,
        parameters=parameters,
        software_version=software_version,
    )


create_multi_source_processing_run = build_multi_source_processing_run
create_longitudinal_record = build_longitudinal_record
create_multi_source_analysis_input = build_multi_source_analysis_input


def build_longitudinal_source_manifest(
    analysis_input: MultiSourceAnalysisInput,
    *,
    parameters: tuple[MetadataEntry, ...] = (),
    software_version: str = RES62_SOFTWARE_VERSION,
) -> LongitudinalSourceManifestResult:
    """Run the registered structural-only RES-62 manifest operation."""

    processing_run = build_multi_source_processing_run(
        analysis_input,
        method=RES62_MULTI_SOURCE_MANIFEST,
        parameters=parameters,
        software_version=software_version,
    )
    graph = build_multi_source_provenance_graph(analysis_input, processing_run)
    selected_observation_ids = analysis_input.source_observation_ids
    selected_entry_hashes = analysis_input.selected_entry_hashes
    return LongitudinalSourceManifestResult(
        analysis_input=analysis_input,
        processing_run=processing_run,
        selected_observation_ids=selected_observation_ids,
        selected_entry_hashes=selected_entry_hashes,
        source_count=len(selected_observation_ids),
        manifest_hash=_manifest_hash(
            analysis_input,
            selected_observation_ids,
            selected_entry_hashes,
        ),
        provenance_graph=graph,
    )


derive_longitudinal_source_manifest = build_longitudinal_source_manifest
build_source_manifest = build_longitudinal_source_manifest
create_longitudinal_source_manifest = build_longitudinal_source_manifest


# The migration name is intentionally explicit in the public API and makes
# the zero-mutation source-observation wrapping path easy to discover.
migrate_scientific_observation_to_longitudinal_entry = build_longitudinal_observation_entry


__all__ = [
    "build_contextualized_scientific_observation",
    "build_longitudinal_observation_entry",
    "build_longitudinal_record",
    "build_longitudinal_source_manifest",
    "build_multi_source_analysis_input",
    "build_multi_source_processing_run",
    "build_source_artifact_qualification_binding",
    "build_source_manifest",
    "create_longitudinal_record",
    "create_longitudinal_source_manifest",
    "create_multi_source_analysis_input",
    "create_multi_source_processing_run",
    "derive_longitudinal_source_manifest",
    "migrate_scientific_observation_to_longitudinal_entry",
]
