"""Family-specific drop-jump event definitions and occurrences."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.drop_jump.identity import (
    DropJumpMeasurementIdentity,
    DropJumpTimebase,
)
from dynamislm.measurement.drop_jump.registry import (
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_DEFINITION,
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_METHOD,
    DROP_JUMP_SOFTWARE_VERSION,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_DEFINITION,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_METHOD,
    DROP_JUMP_TOUCHDOWN_EVENT_DEFINITION,
    DROP_JUMP_TOUCHDOWN_EVENT_METHOD,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    _require_enum,
    _require_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, register_serializable_type


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


class DropJumpEventLabel(StrEnum):
    TOUCHDOWN = "TOUCHDOWN"
    REBOUND_TAKEOFF = "REBOUND_TAKEOFF"
    SUBSEQUENT_LANDING = "SUBSEQUENT_LANDING"


class DropJumpEventOccurrenceStatus(StrEnum):
    VALID = "VALID"
    QUESTIONABLE = "QUESTIONABLE"
    INVALID = "INVALID"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpEventDefinition:
    """Definition of one DJ event label."""

    reference: RegistryReference
    label: DropJumpEventLabel
    description: str

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "event-definition":
            raise ValueError("DJ event definition reference has the wrong object type")
        _require_enum(self.label, DropJumpEventLabel, "label")
        _require_text(self.description, "description")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpEventDetectorParameters:
    """Explicit detector parameters; no threshold or interpolation is implicit."""

    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpEventDetectorMethod:
    """Registered detector identity for one DJ event definition."""

    reference: RegistryReference
    event_definition: DropJumpEventDefinition
    decision_reference: RegistryReference

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "event-method":
            raise ValueError("DJ detector reference has the wrong object type")
        _require_instance(self.event_definition, DropJumpEventDefinition, "event_definition")
        _require_instance(self.decision_reference, RegistryReference, "decision_reference")


DROP_JUMP_TOUCHDOWN_EVENT = DropJumpEventDefinition(
    DROP_JUMP_TOUCHDOWN_EVENT_DEFINITION,
    DropJumpEventLabel.TOUCHDOWN,
    "First registered ground-contact event after step-off.",
)
DROP_JUMP_REBOUND_TAKEOFF_EVENT = DropJumpEventDefinition(
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_DEFINITION,
    DropJumpEventLabel.REBOUND_TAKEOFF,
    "First registered contact-loss event after touchdown during the rebound.",
)
DROP_JUMP_SUBSEQUENT_LANDING_EVENT = DropJumpEventDefinition(
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_DEFINITION,
    DropJumpEventLabel.SUBSEQUENT_LANDING,
    "First registered ground-contact event after rebound takeoff.",
)

DROP_JUMP_TOUCHDOWN_DETECTOR = DropJumpEventDetectorMethod(
    DROP_JUMP_TOUCHDOWN_EVENT_METHOD,
    DROP_JUMP_TOUCHDOWN_EVENT,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
DROP_JUMP_REBOUND_TAKEOFF_DETECTOR = DropJumpEventDetectorMethod(
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_METHOD,
    DROP_JUMP_REBOUND_TAKEOFF_EVENT,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
DROP_JUMP_SUBSEQUENT_LANDING_DETECTOR = DropJumpEventDetectorMethod(
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_METHOD,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)

_DETECTOR_BY_LABEL = {
    DropJumpEventLabel.TOUCHDOWN: DROP_JUMP_TOUCHDOWN_DETECTOR,
    DropJumpEventLabel.REBOUND_TAKEOFF: DROP_JUMP_REBOUND_TAKEOFF_DETECTOR,
    DropJumpEventLabel.SUBSEQUENT_LANDING: DROP_JUMP_SUBSEQUENT_LANDING_DETECTOR,
}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpEventOccurrence:
    """Sample-attached DJ event with complete source and detector lineage."""

    occurrence_id: InstanceIdentifier
    definition: DropJumpEventDefinition
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity: DropJumpMeasurementIdentity
    source_timebase: DropJumpTimebase
    source_series_digest: str
    detector_method: DropJumpEventDetectorMethod
    detector_parameters: DropJumpEventDetectorParameters
    source_sample_count: int
    sample_index: int
    event_time_s: float
    status: DropJumpEventOccurrenceStatus
    qc_codes: tuple[str, ...]
    provenance: Provenance
    preceding_event_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        if self.occurrence_id.instance_type != "event-occurrence":
            raise ValueError("DJ event occurrence ID must identify an event occurrence")
        _require_instance(self.definition, DropJumpEventDefinition, "definition")
        if self.detector_method.event_definition != self.definition:
            raise ValueError("DJ event definition must match detector method")
        for name, expected in (
            ("source_observation_id", "observation"),
            ("source_signal_id", "signal"),
            ("source_artifact_id", "artifact"),
            ("source_acquisition_id", "acquisition"),
        ):
            value = getattr(self, name)
            if value.instance_type != expected:
                raise ValueError(f"{name} must identify a {expected}")
        _require_instance(
            self.source_measurement_identity,
            DropJumpMeasurementIdentity,
            "source_measurement_identity",
        )
        _require_instance(self.source_timebase, DropJumpTimebase, "source_timebase")
        _require_text(self.source_series_digest, "source_series_digest")
        _require_instance(self.detector_method, DropJumpEventDetectorMethod, "detector_method")
        _require_instance(
            self.detector_parameters,
            DropJumpEventDetectorParameters,
            "detector_parameters",
        )
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("source_sample_count must be a positive integer")
        if (
            type(self.sample_index) is not int
            or not 0 <= self.sample_index < self.source_sample_count
        ):
            raise ValueError("sample_index must be inside source sample support")
        _finite(self.event_time_s, "event_time_s")
        _require_enum(self.status, DropJumpEventOccurrenceStatus, "status")
        _require_tuple_items(self.qc_codes, str, "qc_codes")
        _require_instance(self.provenance, Provenance, "provenance")
        matching_runs = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_entity_id == self.occurrence_id
        )
        if len(matching_runs) != 1:
            raise ValueError("DJ event occurrence must have exactly one output processing run")
        if matching_runs[0].method != self.detector_method.reference:
            raise ValueError("DJ event processing run method must match detector method")

    @property
    def label(self) -> DropJumpEventLabel:
        return self.definition.label


def _event_provenance(
    source: Provenance,
    *,
    occurrence_id: InstanceIdentifier,
    source_observation_id: InstanceIdentifier,
    detector: DropJumpEventDetectorMethod,
    parameters: DropJumpEventDetectorParameters,
) -> Provenance:
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", occurrence_id.value),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in source.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=detector.reference,
        parameters=parameters.parameters,
        software_version=DROP_JUMP_SOFTWARE_VERSION,
        output_entity_id=occurrence_id,
    )
    if not run.source_artifact_ids:
        raise ValueError("DJ event requires source artifact provenance")
    edges = list(source.lineage_edges)
    for artifact_id in run.source_artifact_ids:
        edge = LineageEdge(
            artifact_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for source_id in (
        source_observation_id,
        *tuple(item.artifact_id for item in source.source_artifacts),
        *tuple(item.acquisition_id for item in source.acquisitions),
    ):
        edge = LineageEdge(
            source_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for evidence in (EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),):
        edge = LineageEdge(
            evidence.reference.stable_id,
            run.processing_run_id.qualified,
            LineageRelation.SUPPORTED_BY,
        )
        if edge not in edges:
            edges.append(edge)
    output_edge = LineageEdge(
        run.processing_run_id.qualified,
        occurrence_id.qualified,
        LineageRelation.PRODUCED,
    )
    if output_edge not in edges:
        edges.append(output_edge)
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", occurrence_id.value),
        source_artifacts=source.source_artifacts,
        acquisitions=source.acquisitions,
        processing_runs=(*source.processing_runs, run),
        lineage_edges=tuple(edges),
        evidence_references=(
            *source.evidence_references,
            EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),
        ),
        metrological_traceability=source.metrological_traceability,
        recorded_at=source.recorded_at,
    )


def build_drop_jump_event_occurrence(
    *,
    source_observation: ScientificMeasurementObservation,
    label: DropJumpEventLabel,
    sample_index: int,
    source_sample_count: int,
    source_series_digest: str,
    detector_parameters: DropJumpEventDetectorParameters | None = None,
    status: DropJumpEventOccurrenceStatus = DropJumpEventOccurrenceStatus.VALID,
    qc_codes: tuple[str, ...] = (),
    occurrence_id: InstanceIdentifier | None = None,
    preceding_event_id: InstanceIdentifier | None = None,
) -> DropJumpEventOccurrence:
    """Bind an already-detected sample to a registered DJ event method.

    This constructor records the exact supplied event; it does not sort,
    interpolate, backshift, or repair a caller's event.
    """

    if not isinstance(source_observation, ScientificMeasurementObservation):
        raise ValueError("source_observation must be a scientific observation")
    if not isinstance(source_observation.identity, DropJumpMeasurementIdentity):
        raise ValueError("source observation must carry DropJumpMeasurementIdentity")
    _require_enum(label, DropJumpEventLabel, "label")
    if type(sample_index) is not int or sample_index < 0:
        raise ValueError("sample_index must be a non-negative integer")
    if type(source_sample_count) is not int or source_sample_count < 1:
        raise ValueError("source_sample_count must be a positive integer")
    if sample_index >= source_sample_count:
        raise ValueError("sample_index must be inside source sample support")
    _require_text(source_series_digest, "source_series_digest")
    timebase = source_observation.identity.acquisition.timebase
    if timebase is None:
        raise ValueError("DJ event source requires an explicit acquisition timebase")
    if source_observation.identity.acquisition.raw_artifact is None:
        raise ValueError("DJ event source requires a raw artifact identity")
    if source_observation.identity.acquisition.acquisition_instance_id is None:
        raise ValueError("DJ event source requires an acquisition identity")
    if source_observation.identity.acquisition.raw_artifact not in {
        artifact.artifact_id for artifact in source_observation.provenance.source_artifacts
    }:
        raise ValueError("DJ event source artifact is absent from source provenance")
    if source_observation.identity.acquisition.acquisition_instance_id not in {
        acquisition.acquisition_id for acquisition in source_observation.provenance.acquisitions
    }:
        raise ValueError("DJ event source acquisition is absent from source provenance")
    if (
        source_observation.identity.acquisition.source_series_digest is not None
        and source_observation.identity.acquisition.source_series_digest != source_series_digest
    ):
        raise ValueError("DJ event digest does not match source identity")
    detector = _DETECTOR_BY_LABEL[label]
    parameters = detector_parameters or DropJumpEventDetectorParameters()
    event_time = timebase.time_at(sample_index)
    digest = canonical_hash(
        {
            "label": label,
            "sample_index": sample_index,
            "source_observation_id": source_observation.observation_id,
            "source_series_digest": source_series_digest,
            "detector": detector,
            "parameters": parameters,
        }
    ).removeprefix("sha256:")[:24]
    output_id = occurrence_id or InstanceIdentifier("event-occurrence", f"drop-jump:{digest}")
    if output_id.instance_type != "event-occurrence":
        raise ValueError("occurrence_id must identify an event occurrence")
    signal_id = InstanceIdentifier(
        "signal", f"drop-jump:{source_series_digest.removeprefix('sha256:')[:24]}"
    )
    return DropJumpEventOccurrence(
        occurrence_id=output_id,
        definition=detector.event_definition,
        source_observation_id=source_observation.observation_id,
        source_signal_id=signal_id,
        source_artifact_id=source_observation.identity.acquisition.raw_artifact,
        source_acquisition_id=source_observation.identity.acquisition.acquisition_instance_id,
        source_measurement_identity=source_observation.identity,
        source_timebase=timebase,
        source_series_digest=source_series_digest,
        detector_method=detector,
        detector_parameters=parameters,
        source_sample_count=source_sample_count,
        sample_index=sample_index,
        event_time_s=event_time,
        status=status,
        qc_codes=qc_codes,
        provenance=_event_provenance(
            source_observation.provenance,
            occurrence_id=output_id,
            source_observation_id=source_observation.observation_id,
            detector=detector,
            parameters=parameters,
        ),
        preceding_event_id=preceding_event_id,
    )


def _event_refusal(
    claim: str,
    reasons: tuple[RefusalReasonCode | str, ...],
    missing: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult:
    codes = tuple(item.value if isinstance(item, RefusalReasonCode) else item for item in reasons)
    digest = canonical_hash(
        {"claim": claim, "reasons": codes, "missing": missing, "observations": observation_ids}
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"drop-jump-event:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing,
        what_can_still_be_safely_described=("the supplied DJ event identities and recorded times",),
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        observation_ids=observation_ids,
    )


def validate_drop_jump_event_order(
    occurrences: tuple[DropJumpEventOccurrence, ...],
) -> RefusalResult | None:
    """Validate TOUCHDOWN < REBOUND_TAKEOFF < SUBSEQUENT_LANDING without repair."""

    claim = "validate drop-jump event order"
    try:
        require_tuple(occurrences, "occurrences")
        if len(occurrences) != 3:
            return _event_refusal(
                claim,
                (RefusalReasonCode.EVENT_ORDER_INVALID,),
                ("exactly TOUCHDOWN, REBOUND_TAKEOFF and SUBSEQUENT_LANDING",),
                tuple(item.source_observation_id for item in occurrences),
            )
        if any(not isinstance(item, DropJumpEventOccurrence) for item in occurrences):
            return _event_refusal(
                claim,
                (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
                ("DropJumpEventOccurrence values",),
                (),
            )
        first = occurrences[0]
        expected = (
            DropJumpEventLabel.TOUCHDOWN,
            DropJumpEventLabel.REBOUND_TAKEOFF,
            DropJumpEventLabel.SUBSEQUENT_LANDING,
        )
        if tuple(item.label for item in occurrences) != expected:
            return _event_refusal(
                claim,
                (RefusalReasonCode.EVENT_ORDER_INVALID,),
                ("TOUCHDOWN < REBOUND_TAKEOFF < SUBSEQUENT_LANDING",),
                tuple(item.source_observation_id for item in occurrences),
            )
        if any(
            item.source_observation_id != first.source_observation_id
            or item.source_signal_id != first.source_signal_id
            or item.source_artifact_id != first.source_artifact_id
            or item.source_acquisition_id != first.source_acquisition_id
            or item.source_measurement_identity != first.source_measurement_identity
            or item.source_timebase != first.source_timebase
            or item.source_series_digest != first.source_series_digest
            or item.sample_index <= occurrences[index - 1].sample_index
            or item.event_time_s <= occurrences[index - 1].event_time_s
            for index, item in enumerate(occurrences[1:], start=1)
        ):
            return _event_refusal(
                claim,
                (RefusalReasonCode.EVENT_SOURCE_MISMATCH, RefusalReasonCode.EVENT_ORDER_INVALID),
                ("same DJ source and strict sample/time ordering",),
                tuple(item.source_observation_id for item in occurrences),
            )
        return None
    except (TypeError, ValueError, AttributeError):
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_SOURCE_MISMATCH,),
            ("iterable tuple of typed DJ event occurrences",),
            (),
        )


__all__ = [
    "DROP_JUMP_REBOUND_TAKEOFF_DETECTOR",
    "DROP_JUMP_REBOUND_TAKEOFF_EVENT",
    "DROP_JUMP_SUBSEQUENT_LANDING_DETECTOR",
    "DROP_JUMP_SUBSEQUENT_LANDING_EVENT",
    "DROP_JUMP_TOUCHDOWN_DETECTOR",
    "DROP_JUMP_TOUCHDOWN_EVENT",
    "DropJumpEventDefinition",
    "DropJumpEventDetectorMethod",
    "DropJumpEventDetectorParameters",
    "DropJumpEventLabel",
    "DropJumpEventOccurrence",
    "DropJumpEventOccurrenceStatus",
    "build_drop_jump_event_occurrence",
    "validate_drop_jump_event_order",
]
