"""Family-specific drop-jump event definitions and occurrences."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.drop_jump.identity import (
    DropJumpAcquisitionRecord,
    DropJumpMeasurementIdentity,
    DropJumpSourceArtifact,
    DropJumpTimebase,
)
from dynamislm.measurement.drop_jump.registry import (
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_DEFINITION,
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_METHOD,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_DEFINITION,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_METHOD,
    DROP_JUMP_TEST_FAMILY,
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
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.taxonomy import ValueOrigin
from dynamislm.provenance.models import (
    LineageRelation,
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
class DropJumpEventSourceEvidence:
    """Upstream declaration that gives one DJ event occurrence authority."""

    source_event_id: InstanceIdentifier
    source_context: ObservationContext
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity: DropJumpMeasurementIdentity
    source_timebase: DropJumpTimebase
    source_series_digest: str
    source_sample_count: int
    label: DropJumpEventLabel
    sample_index: int
    event_time_s: float
    detector_method: DropJumpEventDetectorMethod
    detector_parameters: DropJumpEventDetectorParameters
    status: DropJumpEventOccurrenceStatus
    qc_codes: tuple[str, ...]
    source_value_origin: ValueOrigin
    upstream_processing_run_id: InstanceIdentifier
    provenance: Provenance
    preceding_event_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        _require_instance(self.source_event_id, InstanceIdentifier, "source_event_id")
        if self.source_event_id.instance_type != "event-occurrence":
            raise ValueError("source_event_id must identify an event occurrence")
        _require_instance(self.source_context, ObservationContext, "source_context")
        for field_name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
        ):
            _require_instance(value, InstanceIdentifier, field_name)
            if value.instance_type != expected:
                raise ValueError(f"{field_name} must identify a {expected}")
        _require_instance(
            self.source_measurement_identity,
            DropJumpMeasurementIdentity,
            "source_measurement_identity",
        )
        _require_instance(self.source_timebase, DropJumpTimebase, "source_timebase")
        _require_text(self.source_series_digest, "source_series_digest")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("source_sample_count must be positive")
        _require_enum(self.label, DropJumpEventLabel, "label")
        if (
            type(self.sample_index) is not int
            or self.sample_index < 0
            or self.sample_index >= self.source_sample_count
        ):
            raise ValueError("source event sample_index must be inside source sample support")
        _finite(self.event_time_s, "source event time")
        if self.source_timebase.time_at(self.sample_index) != self.event_time_s:
            raise ValueError("source event time must equal the exact source timebase sample")
        _require_instance(self.detector_method, DropJumpEventDetectorMethod, "detector_method")
        if self.detector_method != _DETECTOR_BY_LABEL[self.label]:
            raise ValueError("source event detector method is not the registered DJ method")
        if self.detector_method.event_definition.label is not self.label:
            raise ValueError("source event label does not match detector method")
        _require_instance(
            self.detector_parameters,
            DropJumpEventDetectorParameters,
            "detector_parameters",
        )
        _require_enum(self.status, DropJumpEventOccurrenceStatus, "status")
        _require_tuple_items(self.qc_codes, str, "qc_codes")
        _require_enum(self.source_value_origin, ValueOrigin, "source_value_origin")
        if self.source_value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("DJ event source origin must remain source/provider-origin")
        _require_instance(
            self.upstream_processing_run_id,
            InstanceIdentifier,
            "upstream_processing_run_id",
        )
        if self.upstream_processing_run_id.instance_type != "processing-run":
            raise ValueError("upstream_processing_run_id must identify a processing run")
        _require_instance(self.provenance, Provenance, "provenance")
        expected_signal_id = InstanceIdentifier(
            "signal", f"drop-jump:{self.source_series_digest.removeprefix('sha256:')[:24]}"
        )
        if self.source_signal_id != expected_signal_id:
            raise ValueError("source event signal does not preserve source-series identity")
        source_artifacts = tuple(
            item
            for item in self.provenance.source_artifacts
            if item.artifact_id == self.source_artifact_id
        )
        source_acquisitions = tuple(
            item
            for item in self.provenance.acquisitions
            if item.acquisition_id == self.source_acquisition_id
        )
        if (
            len(source_artifacts) != 1
            or not isinstance(source_artifacts[0], DropJumpSourceArtifact)
            or not source_artifacts[0].immutable
            or source_artifacts[0].status.value != "VERIFIED"
            or source_artifacts[0].content_digest != self.source_series_digest
            or len(source_acquisitions) != 1
            or not isinstance(source_acquisitions[0], DropJumpAcquisitionRecord)
        ):
            raise ValueError("source event provenance must preserve a verified source series")
        run = next(
            (
                item
                for item in self.provenance.processing_runs
                if item.output_entity_id == self.source_event_id
            ),
            None,
        )
        if run is None or run.processing_run_id != self.upstream_processing_run_id:
            raise ValueError("source event provenance must preserve its producing run")
        if run.method != self.detector_method.reference:
            raise ValueError("source event producing run method does not match detector")
        if run.parameters != _event_source_parameters(self):
            raise ValueError("source event producing run parameters do not reproduce")
        if self.source_artifact_id not in run.source_artifact_ids:
            raise ValueError("source event producing run omits source artifact")
        for from_id, relation in (
            (self.source_observation_id.qualified, LineageRelation.DERIVED_FROM),
            (self.source_signal_id.qualified, LineageRelation.DERIVED_FROM),
            (self.source_artifact_id.qualified, LineageRelation.DERIVED_FROM),
            (self.source_acquisition_id.qualified, LineageRelation.DERIVED_FROM),
            (self.detector_method.decision_reference.stable_id, LineageRelation.SUPPORTED_BY),
        ):
            if not any(
                edge.from_id == from_id
                and edge.to_id == run.processing_run_id.qualified
                and edge.relation is relation
                for edge in self.provenance.lineage_edges
            ):
                raise ValueError("source event provenance omits an authority lineage edge")
        if not any(
            edge.from_id == run.processing_run_id.qualified
            and edge.to_id == self.source_event_id.qualified
            and edge.relation is LineageRelation.PRODUCED
            for edge in self.provenance.lineage_edges
        ):
            raise ValueError("source event provenance omits the produced event edge")
        if self.preceding_event_id is not None:
            _require_instance(self.preceding_event_id, InstanceIdentifier, "preceding_event_id")
            if self.preceding_event_id.instance_type != "event-occurrence":
                raise ValueError("preceding_event_id must identify an event occurrence")


def _event_source_parameters(
    source: DropJumpEventSourceEvidence,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("source_event_id", source.source_event_id.qualified),
        MetadataEntry("source_observation_id", source.source_observation_id.qualified),
        MetadataEntry("source_signal_id", source.source_signal_id.qualified),
        MetadataEntry("source_artifact_id", source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", source.source_acquisition_id.qualified),
        MetadataEntry("source_series_digest", source.source_series_digest),
        MetadataEntry("source_sample_count", source.source_sample_count),
        MetadataEntry("label", source.label.value),
        MetadataEntry("sample_index", source.sample_index),
        MetadataEntry("event_time_s", source.event_time_s),
        MetadataEntry("detector_parameters", canonical_hash(source.detector_parameters)),
        MetadataEntry("status", source.status.value),
        MetadataEntry("qc_codes", canonical_hash(source.qc_codes)),
        MetadataEntry("source_value_origin", source.source_value_origin.value),
        MetadataEntry(
            "preceding_event_id",
            source.preceding_event_id.qualified if source.preceding_event_id is not None else None,
        ),
    )


def _validate_event_source_evidence(
    source: DropJumpEventSourceEvidence,
    source_observation: ScientificMeasurementObservation,
) -> None:
    _require_instance(source, DropJumpEventSourceEvidence, "source_event_evidence")
    _require_instance(source_observation, ScientificMeasurementObservation, "source_observation")
    identity = source_observation.identity
    if not isinstance(identity, DropJumpMeasurementIdentity):
        raise ValueError("DJ event source observation requires DJ identity")
    if (
        source.source_context != source_observation.context
        or source.source_observation_id != source_observation.observation_id
        or source.source_measurement_identity != identity
        or source.source_timebase != identity.acquisition.timebase
    ):
        raise ValueError("DJ event source is not bound to the source observation")
    if source_observation.result.status.name != "VALID":
        raise ValueError("DJ event source observation must be valid")
    if source_observation.result.classification.value_origin is not source.source_value_origin:
        raise ValueError("DJ event source origin does not match source observation")
    if (
        identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
        or source.source_measurement_identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
    ):
        raise ValueError("DJ event source identity has an inconsistent family")
    source_artifacts = tuple(
        item
        for item in source.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    source_acquisitions = tuple(
        item
        for item in source.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    if len(source_artifacts) != 1 or not isinstance(source_artifacts[0], DropJumpSourceArtifact):
        raise ValueError("DJ event source provenance must preserve a typed source artifact")
    if (
        not source_artifacts[0].immutable
        or source_artifacts[0].status.value != "VERIFIED"
        or len(source_acquisitions) != 1
        or not isinstance(source_acquisitions[0], DropJumpAcquisitionRecord)
    ):
        raise ValueError("DJ event source provenance must preserve verified artifact/acquisition")
    observation_artifacts = tuple(
        item
        for item in source_observation.provenance.source_artifacts
        if item.artifact_id == source.source_artifact_id
    )
    observation_acquisitions = tuple(
        item
        for item in source_observation.provenance.acquisitions
        if item.acquisition_id == source.source_acquisition_id
    )
    if observation_artifacts != source_artifacts or observation_acquisitions != source_acquisitions:
        raise ValueError("DJ event source is not bound to source provenance")
    if source_artifacts[0].content_digest != source.source_series_digest:
        raise ValueError("DJ event source digest does not match source artifact")
    if (
        identity.acquisition.source_series_digest is not None
        and identity.acquisition.source_series_digest != source.source_series_digest
    ):
        raise ValueError("DJ event source digest does not match source identity")
    run = next(
        (
            item
            for item in source.provenance.processing_runs
            if item.output_entity_id == source.source_event_id
        ),
        None,
    )
    if run is None or run.processing_run_id != source.upstream_processing_run_id:
        raise ValueError("DJ event source provenance must preserve its producing run")
    if run.method != source.detector_method.reference:
        raise ValueError("DJ event source run method does not match detector method")
    if run.parameters != _event_source_parameters(source):
        raise ValueError("DJ event source run parameters do not reproduce")
    if source.source_artifact_id not in run.source_artifact_ids:
        raise ValueError("DJ event source run omits source artifact")
    for from_id, relation in (
        (source.source_observation_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_signal_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_artifact_id.qualified, LineageRelation.DERIVED_FROM),
        (source.source_acquisition_id.qualified, LineageRelation.DERIVED_FROM),
        (source.detector_method.decision_reference.stable_id, LineageRelation.SUPPORTED_BY),
    ):
        if not any(
            edge.from_id == from_id
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is relation
            for edge in source.provenance.lineage_edges
        ):
            raise ValueError("DJ event source provenance omits an authority lineage edge")
    if not any(
        edge.from_id == run.processing_run_id.qualified
        and edge.to_id == source.source_event_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in source.provenance.lineage_edges
    ):
        raise ValueError("DJ event source provenance omits the produced event edge")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpEventOccurrence:
    """Sample-attached DJ event preserving upstream detector lineage."""

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
    source_evidence: DropJumpEventSourceEvidence | None = None

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
        source_evidence = self.source_evidence
        if not isinstance(source_evidence, DropJumpEventSourceEvidence):
            raise ValueError("source_evidence must be DropJumpEventSourceEvidence")
        if (
            source_evidence.source_event_id != self.occurrence_id
            or source_evidence.source_observation_id != self.source_observation_id
            or source_evidence.source_signal_id != self.source_signal_id
            or source_evidence.source_artifact_id != self.source_artifact_id
            or source_evidence.source_acquisition_id != self.source_acquisition_id
            or source_evidence.source_measurement_identity != self.source_measurement_identity
            or source_evidence.source_timebase != self.source_timebase
            or source_evidence.source_series_digest != self.source_series_digest
            or source_evidence.source_sample_count != self.source_sample_count
            or source_evidence.label is not self.label
            or source_evidence.sample_index != self.sample_index
            or source_evidence.event_time_s != self.event_time_s
            or source_evidence.detector_method != self.detector_method
            or source_evidence.detector_parameters != self.detector_parameters
            or source_evidence.status is not self.status
            or source_evidence.qc_codes != self.qc_codes
            or source_evidence.preceding_event_id != self.preceding_event_id
            or self.provenance != source_evidence.provenance
        ):
            raise ValueError("DJ event occurrence does not preserve upstream source evidence")
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


def build_drop_jump_event_occurrence(
    *,
    source_observation: ScientificMeasurementObservation,
    label: DropJumpEventLabel | None = None,
    sample_index: int | None = None,
    source_sample_count: int | None = None,
    source_series_digest: str | None = None,
    detector_parameters: DropJumpEventDetectorParameters | None = None,
    status: DropJumpEventOccurrenceStatus | None = None,
    qc_codes: tuple[str, ...] | None = None,
    occurrence_id: InstanceIdentifier | None = None,
    preceding_event_id: InstanceIdentifier | None = None,
    source_evidence: DropJumpEventSourceEvidence | None = None,
) -> DropJumpEventOccurrence:
    """Normalize an upstream DJ event declaration without claiming detection."""

    if source_evidence is None:
        raise ValueError("typed upstream DJ event source evidence is required")
    _validate_event_source_evidence(source_evidence, source_observation)
    supplied = (
        ("label", label, source_evidence.label),
        ("sample_index", sample_index, source_evidence.sample_index),
        ("source_sample_count", source_sample_count, source_evidence.source_sample_count),
        ("source_series_digest", source_series_digest, source_evidence.source_series_digest),
        ("detector_parameters", detector_parameters, source_evidence.detector_parameters),
        ("status", status, source_evidence.status),
        ("qc_codes", qc_codes, source_evidence.qc_codes),
        ("preceding_event_id", preceding_event_id, source_evidence.preceding_event_id),
    )
    if any(value is not None and value != expected for _, value, expected in supplied):
        raise ValueError("raw DJ event fields must match upstream source evidence")
    output_id = occurrence_id or source_evidence.source_event_id
    if output_id != source_evidence.source_event_id:
        raise ValueError("occurrence_id must preserve the upstream event identity")
    return DropJumpEventOccurrence(
        occurrence_id=output_id,
        definition=source_evidence.detector_method.event_definition,
        source_observation_id=source_evidence.source_observation_id,
        source_signal_id=source_evidence.source_signal_id,
        source_artifact_id=source_evidence.source_artifact_id,
        source_acquisition_id=source_evidence.source_acquisition_id,
        source_measurement_identity=source_evidence.source_measurement_identity,
        source_timebase=source_evidence.source_timebase,
        source_series_digest=source_evidence.source_series_digest,
        detector_method=source_evidence.detector_method,
        detector_parameters=source_evidence.detector_parameters,
        source_sample_count=source_evidence.source_sample_count,
        sample_index=source_evidence.sample_index,
        event_time_s=source_evidence.event_time_s,
        status=source_evidence.status,
        qc_codes=source_evidence.qc_codes,
        provenance=source_evidence.provenance,
        preceding_event_id=source_evidence.preceding_event_id,
        source_evidence=source_evidence,
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
    "DropJumpEventSourceEvidence",
    "build_drop_jump_event_occurrence",
    "validate_drop_jump_event_order",
]
