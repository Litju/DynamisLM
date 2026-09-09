"""Immutable RES-62 longitudinal record, input, processing, and result contracts.

RES-62 composes the existing observation, football-world, population, and
provenance authorities.  None of those leaf objects are copied into a new
flattened schema or changed in place.
"""

from __future__ import annotations

import datetime as datetime_module
import re
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.football.models import AthleteIdentity, FootballWorldContext
from dynamislm.football.validation import (
    validate_football_world_context,
    validate_observation_football_context,
)
from dynamislm.longitudinal.registry import (
    LONGITUDINAL_RECORD_METHOD,
    MULTI_SOURCE_ANALYSIS_INPUT_METHOD,
    RES62_MULTI_SOURCE_MANIFEST,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    require_tuple,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.population.models import (
    CanonicalSourceDecision,
    CanonicalSourceStatus,
    EvidenceClass,
)
from dynamislm.provenance.models import EvidenceReference
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_hash(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical sha256 hash")


def _require_instance_identifier(
    value: object,
    expected_instance_type: str,
    field_name: str,
) -> InstanceIdentifier:
    if not isinstance(value, InstanceIdentifier):
        raise ValueError(f"{field_name} must be an InstanceIdentifier")
    if value.instance_type != expected_instance_type:
        raise ValueError(
            f"{field_name} must identify a {expected_instance_type}, got {value.instance_type!r}"
        )
    return value


def _require_registry_reference(value: object, field_name: str) -> RegistryReference:
    if not isinstance(value, RegistryReference):
        raise ValueError(f"{field_name} must be a RegistryReference")
    return value


def _require_registry_operation(value: RegistryReference, field_name: str) -> None:
    _require_registry_reference(value, field_name)
    if value.identifier.object_type != "registered-operation":
        raise ValueError(f"{field_name} must identify a registered operation")


def _entry_authority_payload(
    observation: ScientificMeasurementObservation,
    football_context: FootballWorldContext,
    source_qualification_bindings: tuple[SourceArtifactQualificationBinding, ...],
) -> dict[str, object]:
    """Return the content that defines an entry, excluding derived entry fields."""

    return {
        "observation": observation,
        "football_context": football_context,
        "source_qualification_bindings": source_qualification_bindings,
    }


def _entry_content_hash(
    observation: ScientificMeasurementObservation,
    football_context: FootballWorldContext,
    source_qualification_bindings: tuple[SourceArtifactQualificationBinding, ...],
) -> str:
    return canonical_hash(
        _entry_authority_payload(observation, football_context, source_qualification_bindings)
    )


def _entry_sort_key(entry: LongitudinalObservationEntry) -> tuple[str, str, str]:
    observed_at = entry.observation.context.observed_at.astimezone(datetime_module.UTC)
    return (
        observed_at.isoformat(timespec="microseconds"),
        entry.observation.observation_id.qualified,
        entry.canonical_entry_hash,
    )


def _require_canonical_entry_order(
    entries: tuple[LongitudinalObservationEntry, ...],
    field_name: str,
) -> None:
    ordered = tuple(sorted(entries, key=_entry_sort_key))
    if entries != ordered:
        raise ValueError(f"{field_name} must use canonical observed_at/observation_id ordering")


def _record_authority_payload(
    origin: LongitudinalRecordOrigin,
    athlete: AthleteIdentity,
    entry_hashes: tuple[str, ...],
    method_reference: RegistryReference,
) -> dict[str, object]:
    return {
        "record_origin": origin,
        "athlete": athlete,
        "entry_hashes": entry_hashes,
        "method_reference": method_reference,
    }


def _record_authority_hash(
    origin: LongitudinalRecordOrigin,
    athlete: AthleteIdentity,
    entry_hashes: tuple[str, ...],
    method_reference: RegistryReference,
) -> str:
    return canonical_hash(
        _record_authority_payload(origin, athlete, entry_hashes, method_reference)
    )


def _analysis_input_authority_payload(
    athlete: AthleteIdentity,
    entries: tuple[LongitudinalObservationEntry, ...],
    scope: MultiSourceAnalysisScope,
    method_reference: RegistryReference,
) -> dict[str, object]:
    return {
        "athlete": athlete,
        "selected_entry_hashes": tuple(entry.canonical_entry_hash for entry in entries),
        "scope": scope,
        "method_reference": method_reference,
    }


def _analysis_input_authority_hash(
    athlete: AthleteIdentity,
    entries: tuple[LongitudinalObservationEntry, ...],
    scope: MultiSourceAnalysisScope,
    method_reference: RegistryReference,
) -> str:
    return canonical_hash(
        _analysis_input_authority_payload(athlete, entries, scope, method_reference)
    )


def _processing_authority_payload(
    analysis_input_id: InstanceIdentifier,
    analysis_input_hash: str,
    source_observation_ids: tuple[InstanceIdentifier, ...],
    method: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    software_version: str,
) -> dict[str, object]:
    return {
        "analysis_input_id": analysis_input_id,
        "analysis_input_hash": analysis_input_hash,
        "source_observation_ids": source_observation_ids,
        "method": method,
        "parameters": parameters,
        "software_version": software_version,
    }


def _processing_authority_hash(
    analysis_input_id: InstanceIdentifier,
    analysis_input_hash: str,
    source_observation_ids: tuple[InstanceIdentifier, ...],
    method: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    software_version: str,
) -> str:
    return canonical_hash(
        _processing_authority_payload(
            analysis_input_id,
            analysis_input_hash,
            source_observation_ids,
            method,
            parameters,
            software_version,
        )
    )


def _processing_output_id(processing_hash: str) -> InstanceIdentifier:
    return InstanceIdentifier(
        "derived-result",
        canonical_hash(
            {
                "processing_identity": processing_hash,
                "output_type": "RES62_STRUCTURAL_LONGITUDINAL_SOURCE_MANIFEST",
            }
        ).removeprefix("sha256:"),
    )


def _manifest_hash(
    analysis_input: MultiSourceAnalysisInput,
    selected_observation_ids: tuple[InstanceIdentifier, ...],
    selected_entry_hashes: tuple[str, ...],
) -> str:
    return canonical_hash(
        {
            "analysis_input_id": analysis_input.analysis_input_id,
            "scope": analysis_input.scope,
            "selected_observation_ids": selected_observation_ids,
            "selected_entry_hashes": selected_entry_hashes,
        }
    )


def _structural_result_content_hash(
    result_id: InstanceIdentifier,
    analysis_input: MultiSourceAnalysisInput,
    processing_run: MultiSourceProcessingRun,
    selected_observation_ids: tuple[InstanceIdentifier, ...],
    selected_entry_hashes: tuple[str, ...],
    source_count: int,
    manifest_hash: str,
) -> str:
    """Hash result content without the graph, whose output node contains this hash."""

    return canonical_hash(
        {
            "result_id": result_id,
            "analysis_input": analysis_input,
            "processing_run": processing_run,
            "selected_observation_ids": selected_observation_ids,
            "selected_entry_hashes": selected_entry_hashes,
            "source_count": source_count,
            "manifest_hash": manifest_hash,
            "method_reference": processing_run.method,
        }
    )


def _validate_record_origin(
    origin: LongitudinalRecordOrigin,
    entries: tuple[LongitudinalObservationEntry, ...],
) -> None:
    decisions = tuple(
        binding.canonical_source_decision
        for entry in entries
        for binding in entry.source_qualification_bindings
    )
    if origin is LongitudinalRecordOrigin.OBSERVED_CANONICAL:
        for decision in decisions:
            if (
                decision.status is not CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
                or decision.evidence_class is not EvidenceClass.CANONICAL_EMPIRICAL_TARGET
            ):
                raise ValueError(
                    "OBSERVED_CANONICAL records require passing canonical empirical "
                    "source decisions"
                )
        return
    if origin is LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC:
        for decision in decisions:
            if (
                decision.status is CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
                or decision.evidence_class is EvidenceClass.CANONICAL_EMPIRICAL_TARGET
            ):
                raise ValueError(
                    "SYNTHETIC_DETERMINISTIC records cannot carry a canonical empirical "
                    "source decision"
                )
        return
    raise ValueError("origin must be a LongitudinalRecordOrigin")


def _validate_artifact_qualification_consistency(
    entries: tuple[LongitudinalObservationEntry, ...],
) -> None:
    """Reject one artifact being silently assigned conflicting source decisions."""

    decisions_by_artifact: dict[str, str] = {}
    for entry in entries:
        for binding in entry.source_qualification_bindings:
            decision_hash = canonical_hash(binding.canonical_source_decision)
            for artifact_id in binding.source_artifact_ids:
                key = artifact_id.qualified
                previous = decisions_by_artifact.get(key)
                if previous is not None and previous != decision_hash:
                    raise ValueError(
                        f"source artifact {key!r} has conflicting qualification decisions"
                    )
                decisions_by_artifact[key] = decision_hash


class LongitudinalRecordOrigin(StrEnum):
    """Whether a record is an observed canonical snapshot or a synthetic fixture."""

    OBSERVED_CANONICAL = "OBSERVED_CANONICAL"
    SYNTHETIC_DETERMINISTIC = "SYNTHETIC_DETERMINISTIC"


# Short aliases keep the contract discoverable without creating another wire enum.
RecordOrigin = LongitudinalRecordOrigin


class MultiSourceAnalysisScope(StrEnum):
    """Explicit temporal scope for selecting observations into an analysis input."""

    SAME_SESSION = "SAME_SESSION"
    WITHIN_SEASON = "WITHIN_SEASON"
    CROSS_SEASON = "CROSS_SEASON"


AnalysisScope = MultiSourceAnalysisScope


class LongitudinalLineageNodeKind(StrEnum):
    SOURCE_ARTIFACT = "SOURCE_ARTIFACT"
    ACQUISITION_RECORD = "ACQUISITION_RECORD"
    SOURCE_PROCESSING_RUN = "SOURCE_PROCESSING_RUN"
    SOURCE_OBSERVATION = "SOURCE_OBSERVATION"
    FOOTBALL_WORLD_CONTEXT = "FOOTBALL_WORLD_CONTEXT"
    SOURCE_QUALIFICATION = "SOURCE_QUALIFICATION"
    LONGITUDINAL_ENTRY = "LONGITUDINAL_ENTRY"
    ANALYSIS_INPUT = "ANALYSIS_INPUT"
    MULTI_SOURCE_PROCESSING_RUN = "MULTI_SOURCE_PROCESSING_RUN"
    DERIVED_RESULT = "DERIVED_RESULT"
    REGISTRY_REFERENCE = "REGISTRY_REFERENCE"


LineageNodeKind = LongitudinalLineageNodeKind


class LongitudinalLineageRelation(StrEnum):
    """Relations used by the additive RES-62 provenance graph."""

    DERIVED_FROM = "DERIVED_FROM"
    ACQUIRED_AS = "ACQUIRED_AS"
    PROCESSED_AS = "PROCESSED_AS"
    PRODUCED = "PRODUCED"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTEXTUALIZED_BY = "CONTEXTUALIZED_BY"
    QUALIFIED_BY = "QUALIFIED_BY"
    SELECTED_AS = "SELECTED_AS"
    ANALYZED_AS = "ANALYZED_AS"


LineageRelation = LongitudinalLineageRelation


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceArtifactQualificationBinding:
    """Binds explicit source artifacts to one existing RES-60 source decision."""

    binding_id: InstanceIdentifier
    canonical_source_decision: CanonicalSourceDecision
    source_artifact_ids: tuple[InstanceIdentifier, ...]
    evidence_references: tuple[EvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        _require_instance_identifier(
            self.binding_id,
            "source-qualification-binding",
            "binding_id",
        )
        if not isinstance(self.canonical_source_decision, CanonicalSourceDecision):
            raise ValueError("canonical_source_decision must be a CanonicalSourceDecision")
        require_tuple(self.source_artifact_ids, "source_artifact_ids")
        if not self.source_artifact_ids:
            raise ValueError("source_artifact_ids must not be empty")
        for artifact_id in self.source_artifact_ids:
            _require_instance_identifier(artifact_id, "artifact", "source_artifact_ids item")
        if len({artifact_id.qualified for artifact_id in self.source_artifact_ids}) != len(
            self.source_artifact_ids
        ):
            raise ValueError("source_artifact_ids must not contain duplicates")
        require_tuple(self.evidence_references, "evidence_references")
        if any(not isinstance(item, EvidenceReference) for item in self.evidence_references):
            raise ValueError("evidence_references must contain EvidenceReference values")

    @classmethod
    def from_decision(
        cls,
        canonical_source_decision: CanonicalSourceDecision,
        source_artifact_ids: tuple[InstanceIdentifier, ...],
        evidence_references: tuple[EvidenceReference, ...] = (),
    ) -> SourceArtifactQualificationBinding:
        """Create a deterministic binding identity from its immutable content."""

        digest = canonical_hash(
            {
                "canonical_source_decision": canonical_source_decision,
                "source_artifact_ids": source_artifact_ids,
                "evidence_references": evidence_references,
            }
        ).removeprefix("sha256:")
        return cls(
            binding_id=InstanceIdentifier("source-qualification-binding", digest),
            canonical_source_decision=canonical_source_decision,
            source_artifact_ids=source_artifact_ids,
            evidence_references=evidence_references,
        )

    @property
    def source_decision(self) -> CanonicalSourceDecision:
        """Readable alias for the bound RES-60 decision."""

        return self.canonical_source_decision

    @property
    def qualification_decision(self) -> CanonicalSourceDecision:
        return self.canonical_source_decision

    @property
    def artifact_ids(self) -> tuple[InstanceIdentifier, ...]:
        return self.source_artifact_ids


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LongitudinalObservationEntry:
    """One unchanged scientific observation placed in one football-world context."""

    observation: ScientificMeasurementObservation
    football_context: FootballWorldContext
    source_qualification_bindings: tuple[SourceArtifactQualificationBinding, ...] = ()
    entry_id: InstanceIdentifier | None = None
    entry_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, ScientificMeasurementObservation):
            raise ValueError("observation must be a ScientificMeasurementObservation")
        if not isinstance(self.football_context, FootballWorldContext):
            raise ValueError("football_context must be a FootballWorldContext")
        validate_football_world_context(self.football_context)
        validate_observation_football_context(
            self.observation.context,
            self.football_context,
        )
        if self.observation.context.observed_at < self.football_context.session.start_at:
            raise ValueError("observation observed_at must not precede session start")
        if (
            self.football_context.session.end_at is not None
            and self.observation.context.observed_at > self.football_context.session.end_at
        ):
            raise ValueError("observation observed_at must not exceed session end")
        require_tuple(self.source_qualification_bindings, "source_qualification_bindings")
        if any(
            not isinstance(item, SourceArtifactQualificationBinding)
            for item in self.source_qualification_bindings
        ):
            raise ValueError(
                "source_qualification_bindings must contain "
                "SourceArtifactQualificationBinding values"
            )

        artifacts = self.observation.provenance.source_artifacts
        if not artifacts:
            raise ValueError("observation provenance must contain at least one source artifact")
        artifact_ids = tuple(item.artifact_id.qualified for item in artifacts)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("observation provenance source artifact IDs must be unique")
        binding_ids = tuple(
            item.binding_id.qualified for item in self.source_qualification_bindings
        )
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("source qualification binding IDs must be unique")
        covered_ids = tuple(
            artifact_id.qualified
            for binding in self.source_qualification_bindings
            for artifact_id in binding.source_artifact_ids
        )
        if len(set(covered_ids)) != len(covered_ids):
            raise ValueError("each source artifact must have exactly one qualification binding")
        if set(covered_ids) != set(artifact_ids):
            missing = sorted(set(artifact_ids) - set(covered_ids))
            extra = sorted(set(covered_ids) - set(artifact_ids))
            raise ValueError(
                f"qualification binding coverage must exactly match observation artifacts; "
                f"missing={missing}, extra={extra}"
            )

        expected_hash = _entry_content_hash(
            self.observation,
            self.football_context,
            self.source_qualification_bindings,
        )
        expected_id = InstanceIdentifier(
            "longitudinal-entry",
            expected_hash.removeprefix("sha256:"),
        )
        if self.entry_id is None:
            object.__setattr__(self, "entry_id", expected_id)
        else:
            _require_instance_identifier(self.entry_id, "longitudinal-entry", "entry_id")
            if self.entry_id != expected_id:
                raise ValueError("entry_id does not match immutable entry content")
        if self.entry_hash is None:
            object.__setattr__(self, "entry_hash", expected_hash)
        else:
            _require_hash(self.entry_hash, "entry_hash")
            if self.entry_hash != expected_hash:
                raise ValueError("entry_hash does not match immutable entry content")

    @property
    def source_observation_id(self) -> InstanceIdentifier:
        return self.observation.observation_id

    @property
    def scientific_observation(self) -> ScientificMeasurementObservation:
        return self.observation

    @property
    def world_context(self) -> FootballWorldContext:
        return self.football_context

    @property
    def qualification_bindings(self) -> tuple[SourceArtifactQualificationBinding, ...]:
        return self.source_qualification_bindings

    @property
    def observed_at(self) -> datetime_module.datetime:
        return self.observation.context.observed_at

    @property
    def session_id(self) -> InstanceIdentifier:
        return self.observation.context.session_id

    @property
    def season_id(self) -> ScientificIdentifier:
        return self.football_context.season.identifier

    @property
    def canonical_entry_hash(self) -> str:
        assert self.entry_hash is not None
        return self.entry_hash

    @property
    def canonical_entry_id(self) -> InstanceIdentifier:
        assert self.entry_id is not None
        return self.entry_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LongitudinalAthletePerformanceRecord:
    """Immutable same-athlete snapshot that may span sessions, teams, and seasons."""

    origin: LongitudinalRecordOrigin
    athlete: AthleteIdentity
    entries: tuple[LongitudinalObservationEntry, ...]
    method_reference: RegistryReference = LONGITUDINAL_RECORD_METHOD
    record_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.origin, LongitudinalRecordOrigin):
            raise ValueError("origin must be a LongitudinalRecordOrigin")
        if not isinstance(self.athlete, AthleteIdentity):
            raise ValueError("athlete must be an AthleteIdentity")
        require_tuple(self.entries, "entries")
        if not self.entries:
            raise ValueError("a longitudinal record must contain at least one entry")
        if any(not isinstance(item, LongitudinalObservationEntry) for item in self.entries):
            raise ValueError("entries must contain LongitudinalObservationEntry values")
        _require_registry_operation(self.method_reference, "method_reference")
        if self.method_reference != LONGITUDINAL_RECORD_METHOD:
            raise ValueError("method_reference must be the registered RES-62 record method")
        _require_canonical_entry_order(self.entries, "entries")
        observation_ids = tuple(item.source_observation_id.qualified for item in self.entries)
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("record entries must have unique observation IDs")
        for entry in self.entries:
            if entry.football_context.athlete.athlete_id != self.athlete.athlete_id:
                raise ValueError("all record entries must belong to the record athlete")
        _validate_artifact_qualification_consistency(self.entries)
        _validate_record_origin(self.origin, self.entries)

        entry_hashes = tuple(item.canonical_entry_hash for item in self.entries)
        expected_hash = _record_authority_hash(
            self.origin,
            self.athlete,
            entry_hashes,
            self.method_reference,
        )
        expected_id = InstanceIdentifier(
            "longitudinal-athlete-record",
            expected_hash.removeprefix("sha256:"),
        )
        if self.record_id is None:
            object.__setattr__(self, "record_id", expected_id)
        else:
            _require_instance_identifier(self.record_id, "longitudinal-athlete-record", "record_id")
            if self.record_id != expected_id:
                raise ValueError("record_id does not match the immutable record snapshot")

    @property
    def record_origin(self) -> LongitudinalRecordOrigin:
        return self.origin

    @property
    def canonical_record_hash(self) -> str:
        return _record_authority_hash(
            self.origin,
            self.athlete,
            tuple(item.canonical_entry_hash for item in self.entries),
            self.method_reference,
        )

    @property
    def observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.source_observation_id for item in self.entries)

    @property
    def session_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(dict.fromkeys(item.session_id for item in self.entries))

    @property
    def season_ids(self) -> tuple[ScientificIdentifier, ...]:
        return tuple(dict.fromkeys(item.season_id for item in self.entries))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MultiSourceAnalysisInput:
    """Immutable self-contained selection of at least two source observations."""

    athlete: AthleteIdentity
    entries: tuple[LongitudinalObservationEntry, ...]
    scope: MultiSourceAnalysisScope
    method_reference: RegistryReference = MULTI_SOURCE_ANALYSIS_INPUT_METHOD
    analysis_input_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.athlete, AthleteIdentity):
            raise ValueError("athlete must be an AthleteIdentity")
        require_tuple(self.entries, "entries")
        if len(self.entries) < 2:
            raise ValueError("MultiSourceAnalysisInput requires at least two source observations")
        if any(not isinstance(item, LongitudinalObservationEntry) for item in self.entries):
            raise ValueError("entries must contain LongitudinalObservationEntry values")
        if not isinstance(self.scope, MultiSourceAnalysisScope):
            raise ValueError("scope must be a MultiSourceAnalysisScope")
        _require_registry_operation(self.method_reference, "method_reference")
        if self.method_reference != MULTI_SOURCE_ANALYSIS_INPUT_METHOD:
            raise ValueError("method_reference must be the registered RES-62 input method")
        _require_canonical_entry_order(self.entries, "entries")
        observation_ids = tuple(item.source_observation_id.qualified for item in self.entries)
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("analysis input entries must have unique observation IDs")
        for entry in self.entries:
            if entry.football_context.athlete.athlete_id != self.athlete.athlete_id:
                raise ValueError("all analysis input entries must belong to one athlete")
        _validate_artifact_qualification_consistency(self.entries)

        session_ids = {item.session_id for item in self.entries}
        season_ids = {item.football_context.season.identifier for item in self.entries}
        if self.scope is MultiSourceAnalysisScope.SAME_SESSION and len(session_ids) != 1:
            raise ValueError("SAME_SESSION input must select exactly one session")
        if self.scope is MultiSourceAnalysisScope.WITHIN_SEASON and len(season_ids) != 1:
            raise ValueError("WITHIN_SEASON input must select exactly one season")
        if self.scope is MultiSourceAnalysisScope.CROSS_SEASON and len(season_ids) < 2:
            raise ValueError("CROSS_SEASON input must select at least two explicit seasons")

        expected_hash = _analysis_input_authority_hash(
            self.athlete,
            self.entries,
            self.scope,
            self.method_reference,
        )
        expected_id = InstanceIdentifier(
            "multi-source-analysis-input",
            expected_hash.removeprefix("sha256:"),
        )
        if self.analysis_input_id is None:
            object.__setattr__(self, "analysis_input_id", expected_id)
        else:
            _require_instance_identifier(
                self.analysis_input_id,
                "multi-source-analysis-input",
                "analysis_input_id",
            )
            if self.analysis_input_id != expected_id:
                raise ValueError(
                    "analysis_input_id does not match selected entry content and scope"
                )

    @property
    def selected_entries(self) -> tuple[LongitudinalObservationEntry, ...]:
        return self.entries

    @property
    def input_id(self) -> InstanceIdentifier:
        assert self.analysis_input_id is not None
        return self.analysis_input_id

    @property
    def input_hash(self) -> str:
        return _analysis_input_authority_hash(
            self.athlete,
            self.entries,
            self.scope,
            self.method_reference,
        )

    @property
    def analysis_input_hash(self) -> str:
        return self.input_hash

    @property
    def source_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.source_observation_id for item in self.entries)

    @property
    def selected_entry_hashes(self) -> tuple[str, ...]:
        return tuple(item.canonical_entry_hash for item in self.entries)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MultiSourceProcessingRun:
    """Immutable registered processing identity for a multi-source operation."""

    analysis_input_id: InstanceIdentifier
    analysis_input_hash: str
    source_observation_ids: tuple[InstanceIdentifier, ...]
    method: RegistryReference
    parameters: tuple[MetadataEntry, ...]
    software_version: str
    processing_run_id: InstanceIdentifier | None = None
    output_entity_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        _require_instance_identifier(
            self.analysis_input_id,
            "multi-source-analysis-input",
            "analysis_input_id",
        )
        _require_hash(self.analysis_input_hash, "analysis_input_hash")
        require_tuple(self.source_observation_ids, "source_observation_ids")
        if len(self.source_observation_ids) < 2:
            raise ValueError("multi-source processing requires at least two observations")
        for observation_id in self.source_observation_ids:
            _require_instance_identifier(
                observation_id, "observation", "source_observation_ids item"
            )
        if len({item.qualified for item in self.source_observation_ids}) != len(
            self.source_observation_ids
        ):
            raise ValueError("source_observation_ids must be unique")
        canonical_source_ids = tuple(
            sorted(self.source_observation_ids, key=lambda item: item.qualified)
        )
        if self.source_observation_ids != canonical_source_ids:
            object.__setattr__(self, "source_observation_ids", canonical_source_ids)
        _require_registry_operation(self.method, "method")
        require_tuple(self.parameters, "parameters")
        if any(not isinstance(item, MetadataEntry) for item in self.parameters):
            raise ValueError("parameters must contain MetadataEntry values")
        _require_text(self.software_version, "software_version")

        expected_hash = _processing_authority_hash(
            self.analysis_input_id,
            self.analysis_input_hash,
            self.source_observation_ids,
            self.method,
            self.parameters,
            self.software_version,
        )
        expected_id = InstanceIdentifier(
            "multi-source-processing-run",
            expected_hash.removeprefix("sha256:"),
        )
        expected_output_id = _processing_output_id(expected_hash)
        if self.processing_run_id is None:
            object.__setattr__(self, "processing_run_id", expected_id)
        else:
            _require_instance_identifier(
                self.processing_run_id,
                "multi-source-processing-run",
                "processing_run_id",
            )
            if self.processing_run_id != expected_id:
                raise ValueError(
                    "processing_run_id does not match input, method, parameters, and software"
                )
        if self.output_entity_id is None:
            object.__setattr__(self, "output_entity_id", expected_output_id)
        else:
            _require_instance_identifier(
                self.output_entity_id, "derived-result", "output_entity_id"
            )
            if self.output_entity_id != expected_output_id:
                raise ValueError("output_entity_id does not match the processing identity")

    @property
    def registered_operation(self) -> RegistryReference:
        return self.method

    @property
    def run_id(self) -> InstanceIdentifier:
        assert self.processing_run_id is not None
        return self.processing_run_id

    @property
    def input_id(self) -> InstanceIdentifier:
        return self.analysis_input_id

    @property
    def input_hash(self) -> str:
        return self.analysis_input_hash

    @property
    def method_reference(self) -> RegistryReference:
        return self.method

    @property
    def output_id(self) -> InstanceIdentifier:
        assert self.output_entity_id is not None
        return self.output_entity_id

    @property
    def canonical_processing_hash(self) -> str:
        return _processing_authority_hash(
            self.analysis_input_id,
            self.analysis_input_hash,
            self.source_observation_ids,
            self.method,
            self.parameters,
            self.software_version,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LongitudinalLineageNode:
    """One typed graph node with a stable identity and content fingerprint."""

    node_id: str
    kind: LongitudinalLineageNodeKind
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.node_id, "node_id")
        if any(character.isspace() for character in self.node_id):
            raise ValueError("node_id must not contain whitespace")
        if not isinstance(self.kind, LongitudinalLineageNodeKind):
            raise ValueError("kind must be a LongitudinalLineageNodeKind")
        _require_hash(self.content_hash, "content_hash")

    @property
    def content_fingerprint(self) -> str:
        return self.content_hash

    @property
    def node_kind(self) -> LongitudinalLineageNodeKind:
        return self.kind


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LongitudinalLineageEdge:
    """One directed typed edge in the RES-62 provenance DAG."""

    from_id: str
    to_id: str
    relation: LongitudinalLineageRelation

    def __post_init__(self) -> None:
        _require_text(self.from_id, "from_id")
        _require_text(self.to_id, "to_id")
        if self.from_id == self.to_id:
            raise ValueError("lineage edge cannot point to itself")
        if not isinstance(self.relation, LongitudinalLineageRelation):
            raise ValueError("relation must be a LongitudinalLineageRelation")


def _graph_content_payload(
    nodes: tuple[LongitudinalLineageNode, ...],
    edges: tuple[LongitudinalLineageEdge, ...],
) -> dict[str, object]:
    return {"nodes": nodes, "edges": edges}


def _validate_graph_acyclic(
    nodes: tuple[LongitudinalLineageNode, ...],
    edges: tuple[LongitudinalLineageEdge, ...],
) -> None:
    node_ids = {node.node_id for node in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        if edge.from_id not in node_ids or edge.to_id not in node_ids:
            raise ValueError("every lineage edge endpoint must identify an existing node")
        outgoing[edge.from_id].append(edge.to_id)
        indegree[edge.to_id] += 1
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        current = ready.pop(0)
        visited += 1
        for target in sorted(outgoing[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if visited != len(node_ids):
        raise ValueError("multi-source provenance graph must be acyclic")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MultiSourceProvenanceGraph:
    """Canonical, acyclic union of source and RES-62 longitudinal lineage."""

    nodes: tuple[LongitudinalLineageNode, ...]
    edges: tuple[LongitudinalLineageEdge, ...]
    graph_id: InstanceIdentifier | None = None
    graph_hash: str | None = None

    def __post_init__(self) -> None:
        require_tuple(self.nodes, "nodes")
        require_tuple(self.edges, "edges")
        if any(not isinstance(item, LongitudinalLineageNode) for item in self.nodes):
            raise ValueError("nodes must contain LongitudinalLineageNode values")
        if any(not isinstance(item, LongitudinalLineageEdge) for item in self.edges):
            raise ValueError("edges must contain LongitudinalLineageEdge values")
        node_ids = tuple(item.node_id for item in self.nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("graph node IDs must be unique")
        expected_nodes = tuple(
            sorted(self.nodes, key=lambda item: (item.kind.value, item.node_id, item.content_hash))
        )
        if self.nodes != expected_nodes:
            raise ValueError("graph nodes must use canonical kind/ID ordering")
        edge_keys = tuple((item.from_id, item.to_id, item.relation.value) for item in self.edges)
        if len(set(edge_keys)) != len(edge_keys):
            raise ValueError("graph edges must not contain duplicates")
        expected_edges = tuple(
            sorted(self.edges, key=lambda item: (item.from_id, item.to_id, item.relation.value))
        )
        if self.edges != expected_edges:
            raise ValueError("graph edges must use canonical endpoint/relation ordering")
        _validate_graph_acyclic(self.nodes, self.edges)

        expected_hash = canonical_hash(_graph_content_payload(self.nodes, self.edges))
        expected_id = InstanceIdentifier(
            "multi-source-provenance-graph",
            expected_hash.removeprefix("sha256:"),
        )
        if self.graph_hash is None:
            object.__setattr__(self, "graph_hash", expected_hash)
        else:
            _require_hash(self.graph_hash, "graph_hash")
            if self.graph_hash != expected_hash:
                raise ValueError("graph_hash does not match graph nodes and edges")
        if self.graph_id is None:
            object.__setattr__(self, "graph_id", expected_id)
        else:
            _require_instance_identifier(
                self.graph_id,
                "multi-source-provenance-graph",
                "graph_id",
            )
            if self.graph_id != expected_id:
                raise ValueError("graph_id does not match graph nodes and edges")

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(item.node_id for item in self.nodes)

    @property
    def lineage_nodes(self) -> tuple[LongitudinalLineageNode, ...]:
        return self.nodes

    @property
    def lineage_edges(self) -> tuple[LongitudinalLineageEdge, ...]:
        return self.edges


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LongitudinalSourceManifestResult:
    """Structural RES-62 output; it contains no longitudinal performance statistic."""

    analysis_input: MultiSourceAnalysisInput
    processing_run: MultiSourceProcessingRun
    selected_observation_ids: tuple[InstanceIdentifier, ...]
    selected_entry_hashes: tuple[str, ...]
    source_count: int
    manifest_hash: str
    provenance_graph: MultiSourceProvenanceGraph
    result_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.analysis_input, MultiSourceAnalysisInput):
            raise ValueError("analysis_input must be a MultiSourceAnalysisInput")
        if not isinstance(self.processing_run, MultiSourceProcessingRun):
            raise ValueError("processing_run must be a MultiSourceProcessingRun")
        if self.processing_run.method != RES62_MULTI_SOURCE_MANIFEST:
            raise ValueError(
                "LongitudinalSourceManifestResult requires the registered RES-62 manifest method"
            )
        require_tuple(self.selected_observation_ids, "selected_observation_ids")
        if any(
            not isinstance(item, InstanceIdentifier) or item.instance_type != "observation"
            for item in self.selected_observation_ids
        ):
            raise ValueError("selected_observation_ids must contain observation identifiers")
        require_tuple(self.selected_entry_hashes, "selected_entry_hashes")
        for entry_hash in self.selected_entry_hashes:
            _require_hash(entry_hash, "selected_entry_hashes item")
        if isinstance(self.source_count, bool) or not isinstance(self.source_count, int):
            raise ValueError("source_count must be an integer")
        if self.source_count < 2:
            raise ValueError("source_count must be at least two")
        _require_hash(self.manifest_hash, "manifest_hash")
        if not isinstance(self.provenance_graph, MultiSourceProvenanceGraph):
            raise ValueError("provenance_graph must be a MultiSourceProvenanceGraph")

        expected_ids = self.analysis_input.source_observation_ids
        expected_hashes = self.analysis_input.selected_entry_hashes
        if self.selected_observation_ids != expected_ids:
            raise ValueError("selected_observation_ids must match the analysis input exactly")
        if self.selected_entry_hashes != expected_hashes:
            raise ValueError("selected_entry_hashes must match the analysis input exactly")
        if self.source_count != len(expected_ids):
            raise ValueError("source_count must equal the selected observation count")
        if self.processing_run.analysis_input_id != self.analysis_input.analysis_input_id:
            raise ValueError("processing run must reference the embedded analysis input")
        if self.processing_run.analysis_input_hash != self.analysis_input.input_hash:
            raise ValueError("processing run analysis_input_hash must match the embedded input")
        if tuple(sorted(expected_ids, key=lambda item: item.qualified)) != (
            self.processing_run.source_observation_ids
        ):
            raise ValueError("processing run source IDs must match the embedded analysis input")
        expected_manifest = _manifest_hash(
            self.analysis_input,
            self.selected_observation_ids,
            self.selected_entry_hashes,
        )
        if self.manifest_hash != expected_manifest:
            raise ValueError("manifest_hash does not match the selected structural content")
        expected_result_id = self.processing_run.output_id
        if self.result_id is None:
            object.__setattr__(self, "result_id", expected_result_id)
        else:
            _require_instance_identifier(self.result_id, "derived-result", "result_id")
            if self.result_id != expected_result_id:
                raise ValueError("result_id must equal the processing run output entity")

        # Import lazily so the graph builder can compose these model types
        # without introducing an import cycle at module import time.
        from dynamislm.longitudinal.lineage import validate_multi_source_provenance_graph

        validate_multi_source_provenance_graph(
            self.provenance_graph,
            self.analysis_input,
            self.processing_run,
        )

    @property
    def output_entity_id(self) -> InstanceIdentifier:
        assert self.result_id is not None
        return self.result_id

    @property
    def method_reference(self) -> RegistryReference:
        return self.processing_run.method

    @property
    def structural_result_hash(self) -> str:
        assert self.result_id is not None
        return _structural_result_content_hash(
            self.result_id,
            self.analysis_input,
            self.processing_run,
            self.selected_observation_ids,
            self.selected_entry_hashes,
            self.source_count,
            self.manifest_hash,
        )

    @property
    def graph(self) -> MultiSourceProvenanceGraph:
        """Readable alias for the complete additive provenance graph."""

        return self.provenance_graph


StructuralDerivedResult = LongitudinalSourceManifestResult


__all__ = [
    "AnalysisScope",
    "LineageNodeKind",
    "LineageRelation",
    "LongitudinalAthletePerformanceRecord",
    "LongitudinalLineageEdge",
    "LongitudinalLineageNode",
    "LongitudinalLineageNodeKind",
    "LongitudinalLineageRelation",
    "LongitudinalObservationEntry",
    "LongitudinalRecordOrigin",
    "LongitudinalSourceManifestResult",
    "MultiSourceAnalysisInput",
    "MultiSourceAnalysisScope",
    "MultiSourceProcessingRun",
    "MultiSourceProvenanceGraph",
    "RecordOrigin",
    "SourceArtifactQualificationBinding",
    "StructuralDerivedResult",
]
