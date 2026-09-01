"""Immutable raw vertical-force signal representation for CMJ acquisitions."""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass

from dynamislm.measurement.cmj.acquisition import (
    ArtifactHashScope,
    ArtifactStatus,
    CMJSourceArtifact,
    HashAlgorithm,
    SignalProcessingState,
)
from dynamislm.measurement.cmj.identity import CMJMeasurementIdentity
from dynamislm.measurement.cmj.registry import CMJ_RAW_VERTICAL_FORCE_SIGNAL_SCHEMA
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    UnitReference,
    require_tuple,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementResult,
    StructuredOutputReference,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    Provenance,
)
from dynamislm.serialization import canonical_hash, register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RegularTimebase:
    """Regular samples described by an explicit positive sample rate."""

    sample_rate_hz: float
    start_time_s: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.sample_rate_hz, bool) or not isinstance(
            self.sample_rate_hz, int | float
        ):
            raise ValueError("sample_rate_hz must be numeric")
        if isinstance(self.start_time_s, bool) or not isinstance(self.start_time_s, int | float):
            raise ValueError("start_time_s must be numeric")
        if not math.isfinite(self.sample_rate_hz) or self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be finite and positive")
        if not math.isfinite(self.start_time_s):
            raise ValueError("start_time_s must be finite")
        object.__setattr__(self, "sample_rate_hz", float(self.sample_rate_hz))
        object.__setattr__(self, "start_time_s", float(self.start_time_s))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExplicitTimebase:
    """Per-sample timestamps supplied by the acquisition source."""

    times_s: tuple[float, ...]

    def __post_init__(self) -> None:
        require_tuple(self.times_s, "times_s")
        if any(
            isinstance(time, bool) or not isinstance(time, int | float) for time in self.times_s
        ):
            raise ValueError("explicit times must be numeric")
        object.__setattr__(self, "times_s", tuple(float(time) for time in self.times_s))


type SignalTimebase = RegularTimebase | ExplicitTimebase


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class RawVerticalForceSignal:
    """Raw or explicitly unresolved vertical-force samples; no transform is applied."""

    signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    acquisition_identity_id: ScientificIdentifier
    samples: tuple[float, ...]
    timebase: SignalTimebase | None
    channel_id: str | None
    unit: UnitReference | None
    physical_axis: RegistryReference | None
    reference_frame: RegistryReference | None
    sign_convention: SignConvention | None
    processing_state: SignalProcessingState = SignalProcessingState.UNKNOWN

    def __post_init__(self) -> None:
        require_tuple(self.samples, "samples")
        if not self.samples:
            raise ValueError("raw vertical-force signal must contain at least one sample")
        if not isinstance(self.processing_state, SignalProcessingState):
            raise ValueError("processing state must be a registered SignalProcessingState")
        normalized_samples: list[float] = []
        for sample in self.samples:
            if isinstance(sample, bool) or not isinstance(sample, int | float):
                raise ValueError("raw vertical-force samples must be numeric")
            if not math.isfinite(sample):
                raise ValueError("raw vertical-force samples must be finite")
            normalized_samples.append(float(sample))
        object.__setattr__(self, "samples", tuple(normalized_samples))
        if self.channel_id is not None:
            _require_text(self.channel_id, "channel_id")

    def canonical_content_digest(self) -> str:
        """Hash the deterministic sample/timebase representation used by synthetic fixtures."""

        return canonical_hash({"samples": self.samples, "timebase": self.timebase})

    @property
    def is_raw_acquired(self) -> bool:
        """Whether the source explicitly identifies the samples as raw acquired data."""

        return self.processing_state is SignalProcessingState.RAW_ACQUIRED


def source_artifact_for_signal(
    signal: RawVerticalForceSignal,
    *,
    media_type: str = "application/vnd.dynamislm.cmj.vertical-force-series",
    storage_reference: str | None = None,
) -> CMJSourceArtifact:
    """Create an immutable content-addressed artifact for a canonical signal representation."""

    return CMJSourceArtifact(
        artifact_id=signal.source_artifact_id,
        content_digest=signal.canonical_content_digest(),
        media_type=media_type,
        immutable=True,
        hash_algorithm=HashAlgorithm.SHA256,
        hash_scope=ArtifactHashScope.CANONICAL_SIGNAL_REPRESENTATION,
        status=ArtifactStatus.VERIFIED,
        storage_reference=storage_reference,
        acquisition_id=signal.acquisition_id,
    )


def create_cmj_raw_observation(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    identity: CMJMeasurementIdentity,
    signal: RawVerticalForceSignal,
    source_artifact: CMJSourceArtifact,
    acquisition: AcquisitionRecord,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> ScientificMeasurementObservation:
    """Compose one raw acquisition observation without creating a processing run."""

    if not isinstance(source_artifact, CMJSourceArtifact) or not source_artifact.immutable:
        raise ValueError("CMJ raw observation requires an immutable CMJ source artifact")
    if signal.processing_state is not SignalProcessingState.RAW_ACQUIRED:
        raise ValueError("CMJ raw observation requires RAW_ACQUIRED signal state")
    if signal.acquisition_identity_id != identity.identity_id:
        raise ValueError("signal acquisition identity does not match measurement identity")
    if identity.acquisition.raw_artifact != signal.source_artifact_id:
        raise ValueError("measurement identity raw artifact does not match signal")
    if source_artifact.acquisition_id != signal.acquisition_id:
        raise ValueError("source artifact acquisition linkage does not match signal")
    if acquisition.source_artifact_id != source_artifact.artifact_id:
        raise ValueError("acquisition must reference the source artifact")
    if acquisition.acquisition_id != signal.acquisition_id:
        raise ValueError("acquisition ID does not match signal")
    if acquisition.sensor_channel != signal.channel_id:
        raise ValueError("acquisition channel does not match signal channel")

    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", observation_id.value),
        source_artifacts=(source_artifact,),
        acquisitions=(acquisition,),
        processing_runs=(),
        lineage_edges=(
            LineageEdge(
                source_artifact.artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                LineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
        evidence_references=evidence_references,
        recorded_at=recorded_at,
    )
    result = MeasurementResult(
        result_id=result_id,
        value=StructuredOutputReference(
            artifact_id=source_artifact.artifact_id,
            schema=CMJ_RAW_VERTICAL_FORCE_SIGNAL_SCHEMA,
        ),
        unit=signal.unit,
        classification=ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT,
            ScientificRole.PERFORMANCE_OUTCOME,
        ),
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=result,
        provenance=provenance,
    )
