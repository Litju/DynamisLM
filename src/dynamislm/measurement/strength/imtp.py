"""Deterministic IMTP force-time observations and registered metrics.

Only an explicit, narrow method family is implemented here.  The source
series, baseline, onset occurrence, result context, and processing run are all
bound objects; a force scalar with plausible metadata is not an IMTP authority.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import pairwise
from statistics import stdev

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    NormalizationSpec,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    UnitReference,
    VersionIdentity,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.strength.identity import (
    IMTPMeasurementIdentity,
    StrengthArtifactHashScope,
    StrengthArtifactStatus,
    StrengthHashAlgorithm,
    StrengthProcessingIdentity,
    StrengthProcessingState,
    StrengthSensorModality,
    StrengthSourceArtifact,
    StrengthTimebase,
    StrengthTimebaseKind,
    canonical_series_digest,
    time_at,
    validate_series_timebase,
)
from dynamislm.measurement.strength.registry import (
    BODY_MASS_MEASURAND,
    IMTP_BASELINE_OPERATION,
    IMTP_BASELINE_SEGMENT_METHOD,
    IMTP_BEST_PEAK_FORCE_SELECTION,
    IMTP_BODY_MASS_NORMALIZATION_METHOD,
    IMTP_CONSTRUCT,
    IMTP_ENDPOINT_RFD_METHOD,
    IMTP_EXACT_SAMPLE_AT_TIME_METHOD,
    IMTP_FORCE_AT_50_MS_METRIC,
    IMTP_FORCE_AT_100_MS_METRIC,
    IMTP_FORCE_AT_150_MS_METRIC,
    IMTP_FORCE_AT_200_MS_METRIC,
    IMTP_FORCE_AT_TIME_OPERATION,
    IMTP_FORCE_TIME_SERIES_METRIC,
    IMTP_FORCE_TIME_SERIES_SCHEMA,
    IMTP_GROSS_PEAK_FORCE_METRIC,
    IMTP_IMPULSE_0_50_MS_METRIC,
    IMTP_IMPULSE_0_100_MS_METRIC,
    IMTP_IMPULSE_0_150_MS_METRIC,
    IMTP_IMPULSE_0_200_MS_METRIC,
    IMTP_IMPULSE_OPERATION,
    IMTP_INPUT_OPERATION,
    IMTP_MEAN_ALL_ELIGIBLE_SELECTION,
    IMTP_MEAN_BEST_N_SELECTION,
    IMTP_NET_FORCE_ABOVE_BASELINE_MEASURAND,
    IMTP_NET_PEAK_FORCE_METRIC,
    IMTP_NO_INTERPOLATION_METHOD,
    IMTP_NORMALIZED_FORCE_MEASURAND,
    IMTP_NORMALIZED_FORCE_METRIC,
    IMTP_ONSET_BASELINE_FIVE_SD_METHOD,
    IMTP_ONSET_EVENT_DEFINITION,
    IMTP_PROTOCOL_V1,
    IMTP_RFD_0_50_MS_METRIC,
    IMTP_RFD_0_100_MS_METRIC,
    IMTP_RFD_0_150_MS_METRIC,
    IMTP_RFD_0_200_MS_METRIC,
    IMTP_RFD_OPERATION,
    IMTP_SAMPLE_MAXIMUM_METHOD,
    IMTP_SAMPLE_PEAK_FORCE_OPERATION,
    IMTP_TEST_FAMILY,
    IMTP_TRAPEZOIDAL_INTEGRATION_METHOD,
    IMTP_TRIAL_AGGREGATION_OPERATION,
    IMTP_TRIAL_SUPPORT_METHOD,
    IMTP_VERTICAL_FORCE_MEASURAND,
    KILOGRAM,
    NEWTON,
    NEWTON_PER_KILOGRAM,
    NEWTON_PER_SECOND,
    NEWTON_SECOND,
    RES66_DECISION_STRENGTH_IMTP_VBT,
    STRENGTH_REGISTRY_VERSION,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES66_SOFTWARE_VERSION = "dynamislm-res66-1.0.0"
_ALLOWED_WINDOWS_MS = (50, 100, 150, 200)


class IMTPForceQuantity(StrEnum):
    GROSS_VERTICAL_FORCE = "GROSS_VERTICAL_FORCE"
    NET_FORCE_ABOVE_BASELINE = "NET_FORCE_ABOVE_BASELINE"


class IMTPMetric(StrEnum):
    PEAK_FORCE = "PEAK_FORCE"
    FORCE_AT_TIME = "FORCE_AT_TIME"
    IMPULSE = "IMPULSE"
    RFD = "RFD"


class IMTPThresholdDirection(StrEnum):
    ABOVE_THRESHOLD = "ABOVE_THRESHOLD"


class IMTPTrialSelectionRule(StrEnum):
    BEST_PEAK_FORCE = "BEST_PEAK_FORCE"
    MEAN_ALL_ELIGIBLE = "MEAN_ALL_ELIGIBLE"
    MEAN_BEST_N = "MEAN_BEST_N"


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _numeric_scalar(observation: ScientificMeasurementObservation) -> float:
    value = observation.result.value
    if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
        raise ValueError("observation must contain a numeric scalar")
    result = _finite(value.value, "observation scalar")
    return result


def _refusal(
    claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
    safe_descriptions: tuple[str, ...] = (
        "the independently qualified IMTP source remains describable",
        "no unsupported fatigue, readiness, injury-risk, or physiological claim is emitted",
    ),
) -> RefusalResult:
    code_values = tuple(code.value for code in reason_codes)
    digest = canonical_hash(
        {
            "claim": claim,
            "reason_codes": code_values,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res66-imtp:{digest}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=code_values,
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions,
        evidence_references=(
            RegistryReference(
                identifier=RES66_DECISION_STRENGTH_IMTP_VBT.identifier,
                display_label=RES66_DECISION_STRENGTH_IMTP_VBT.display_label,
                reference_ids=RES66_DECISION_STRENGTH_IMTP_VBT.reference_ids,
            ),
        ),
        observation_ids=observation_ids,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPForceTimeSeries:
    """One delivered vertical-force series for exactly one IMTP trial."""

    signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    samples: tuple[float, ...]
    timebase: StrengthTimebase
    unit: UnitReference
    physical_axis: RegistryReference | None = None
    reference_frame: RegistryReference | None = None
    sign_convention: SignConvention | None = None
    processing_state: StrengthProcessingState = StrengthProcessingState.RAW_ACQUIRED

    def __post_init__(self) -> None:
        for field_name, value, expected_type in (
            ("signal_id", self.signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("acquisition_id", self.acquisition_id, "acquisition"),
        ):
            _require_instance(value, InstanceIdentifier, field_name)
            if value.instance_type != expected_type:
                raise ValueError(f"{field_name} must identify a {expected_type}")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("source_measurement_identity_id must identify a measurement")
        require_tuple(self.samples, "samples")
        if not self.samples:
            raise ValueError("IMTP force series must contain samples")
        normalized = tuple(_finite(value, "IMTP force sample") for value in self.samples)
        object.__setattr__(self, "samples", normalized)
        _require_instance(self.timebase, StrengthTimebase, "timebase")
        validate_series_timebase(self.timebase, len(self.samples))
        _require_instance(self.unit, UnitReference, "unit")
        _require_optional_instance(self.physical_axis, RegistryReference, "physical_axis")
        _require_optional_instance(self.reference_frame, RegistryReference, "reference_frame")
        _require_optional_instance(self.sign_convention, SignConvention, "sign_convention")
        _require_enum(self.processing_state, StrengthProcessingState, "processing_state")

    def canonical_content_digest(self) -> str:
        return canonical_series_digest(self.samples, self.timebase, unit=self.unit)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPForceInput:
    """All linked objects required to operate on one IMTP force series."""

    observation: ScientificMeasurementObservation
    identity: IMTPMeasurementIdentity
    series: IMTPForceTimeSeries
    source_artifact: StrengthSourceArtifact
    acquisition: AcquisitionRecord

    @property
    def signal(self) -> IMTPForceTimeSeries:
        return self.series

    @property
    def artifact(self) -> StrengthSourceArtifact:
        return self.source_artifact


def source_artifact_for_imtp_series(
    series: IMTPForceTimeSeries,
    *,
    media_type: str = "application/vnd.dynamislm.imtp.force-time-series",
) -> StrengthSourceArtifact:
    """Create a verified content-addressed artifact for a delivered series."""

    return StrengthSourceArtifact(
        artifact_id=series.source_artifact_id,
        content_digest=series.canonical_content_digest(),
        media_type=media_type,
        immutable=True,
        hash_algorithm=StrengthHashAlgorithm.SHA256,
        hash_scope=StrengthArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
        status=StrengthArtifactStatus.VERIFIED,
    )


def _source_origin(processing_state: StrengthProcessingState) -> ValueOrigin:
    if processing_state is StrengthProcessingState.RAW_ACQUIRED:
        return ValueOrigin.DIRECT_MEASUREMENT
    if processing_state in {
        StrengthProcessingState.DEVICE_PROCESSED,
        StrengthProcessingState.PROVIDER_PROCESSED,
    }:
        return ValueOrigin.PROVIDER_DERIVED
    raise ValueError("unresolved IMTP processing state cannot create source authority")


def create_imtp_force_input(
    *,
    observation_id: InstanceIdentifier,
    result_id: InstanceIdentifier,
    context: ObservationContext,
    identity: IMTPMeasurementIdentity,
    series: IMTPForceTimeSeries,
    source_artifact: StrengthSourceArtifact,
    acquisition: AcquisitionRecord,
    evidence_references: tuple[EvidenceReference, ...] = (),
    recorded_at: datetime_module.datetime | None = None,
) -> IMTPForceInput:
    """Bind a force series to an IMTP observation and immutable provenance."""

    _validate_imtp_identity(identity)
    if (
        not source_artifact.immutable
        or source_artifact.status is not StrengthArtifactStatus.VERIFIED
    ):
        raise ValueError("IMTP source artifact must be immutable and verified")
    if source_artifact.artifact_id != series.source_artifact_id:
        raise ValueError("IMTP artifact ID does not match the delivered series")
    if source_artifact.content_digest != series.canonical_content_digest():
        raise ValueError("IMTP source artifact digest does not match the delivered series")
    if identity.identity_id != series.source_measurement_identity_id:
        raise ValueError("IMTP series identity does not match the measurement identity")
    if identity.acquisition.raw_artifact != series.source_artifact_id:
        raise ValueError("IMTP measurement identity does not name the series artifact")
    if identity.acquisition.acquisition_instance_id != acquisition.acquisition_id:
        raise ValueError("IMTP acquisition identity does not match the acquisition record")
    if acquisition.source_artifact_id != source_artifact.artifact_id:
        raise ValueError("IMTP acquisition record does not reference the source artifact")
    if acquisition.acquisition_id != series.acquisition_id:
        raise ValueError("IMTP acquisition ID does not match the delivered series")
    if acquisition.sensor_channel != identity.acquisition.sensor_channel:
        raise ValueError("IMTP acquisition channel does not match the identity")
    if identity.acquisition.timebase != series.timebase:
        raise ValueError("IMTP identity timebase does not match the delivered series")
    if identity.acquisition.unit != series.unit:
        raise ValueError("IMTP identity unit does not match the delivered series")
    if observation_id.instance_type != "observation":
        raise ValueError("IMTP observation ID must identify an observation")
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
            LineageEdge(
                series.signal_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
        evidence_references=evidence_references,
        recorded_at=recorded_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=result_id,
            value=StructuredOutputReference(
                artifact_id=source_artifact.artifact_id,
                schema=IMTP_FORCE_TIME_SERIES_SCHEMA,
            ),
            unit=series.unit,
            classification=ScientificClassification(_source_origin(series.processing_state), ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return IMTPForceInput(observation, identity, series, source_artifact, acquisition)


create_imtp_raw_observation = create_imtp_force_input


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPBaselineSegment:
    """Explicit half-open source segment used to form the baseline."""

    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    start_index: int
    end_index: int
    selection_method: RegistryReference = IMTP_BASELINE_SEGMENT_METHOD
    selection_parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.source_signal_id.instance_type != "signal":
            raise ValueError("baseline source_signal_id must identify a signal")
        if self.source_artifact_id.instance_type != "artifact":
            raise ValueError("baseline source_artifact_id must identify an artifact")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("baseline source identity must identify a measurement")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("baseline indices must be integers")
        if self.start_index < 0 or self.end_index <= self.start_index:
            raise ValueError("baseline must satisfy 0 <= start_index < end_index")
        if self.selection_method != IMTP_BASELINE_SEGMENT_METHOD:
            raise ValueError("baseline selection method is not registered")
        _require_tuple_items(self.selection_parameters, MetadataEntry, "selection_parameters")

    @property
    def sample_count(self) -> int:
        return self.end_index - self.start_index


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPBaselineQC:
    """Deterministic descriptive statistics for the registered baseline segment."""

    sample_count: int
    elapsed_sample_span_s: float
    mean_force_n: float
    standard_deviation_n: float
    range_n: float

    def __post_init__(self) -> None:
        if type(self.sample_count) is not int or self.sample_count < 2:
            raise ValueError("baseline QC requires at least two samples")
        for field_name in (
            "elapsed_sample_span_s",
            "mean_force_n",
            "standard_deviation_n",
            "range_n",
        ):
            value = _finite(getattr(self, field_name), field_name)
            if (
                field_name in {"elapsed_sample_span_s", "standard_deviation_n", "range_n"}
                and value < 0
            ):
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPBaseline:
    """Qualified baseline statistics with the processing run that produced them."""

    baseline_id: InstanceIdentifier
    source_context: ObservationContext
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    segment: IMTPBaselineSegment
    qc: IMTPBaselineQC
    processing_run_id: InstanceIdentifier
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.baseline_id.instance_type != "imtp-baseline":
            raise ValueError("baseline_id must identify an IMTP baseline")
        for field_name, value, expected_type in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
        ):
            if value.instance_type != expected_type:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("baseline source identity must identify a measurement")
        if (
            self.segment.source_signal_id != self.source_signal_id
            or self.segment.source_artifact_id != self.source_artifact_id
            or self.segment.source_measurement_identity_id != self.source_measurement_identity_id
        ):
            raise ValueError("baseline segment is not bound to the baseline source")
        if self.segment.sample_count != self.qc.sample_count:
            raise ValueError("baseline QC count does not match its segment")
        if self.processing_run_id.instance_type != "processing-run":
            raise ValueError("processing_run_id must identify a processing run")
        matching = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_entity_id == self.baseline_id
        )
        if len(matching) != 1 or matching[0].processing_run_id != self.processing_run_id:
            raise ValueError("baseline must preserve one producing processing run")
        if matching[0].method != IMTP_BASELINE_OPERATION:
            raise ValueError("baseline producing run must use the registered baseline operation")
        parameters = {entry.key: entry.value for entry in matching[0].parameters}
        expected: dict[str, object] = {
            "source_observation_id": self.source_observation_id.qualified,
            "source_signal_id": self.source_signal_id.qualified,
            "source_artifact_id": self.source_artifact_id.qualified,
            "source_acquisition_id": self.source_acquisition_id.qualified,
            "source_measurement_identity_id": self.source_measurement_identity_id.stable_id,
            "segment": canonical_json(self.segment),
            "mean_force_n": self.qc.mean_force_n,
            "standard_deviation_n": self.qc.standard_deviation_n,
        }
        for key, expected_value in expected.items():
            if parameters.get(key) != expected_value:
                raise ValueError(f"baseline processing run does not preserve {key}")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPOnsetParameters:
    """Complete V1 onset parameters; no threshold or dwell is implicit."""

    sigma_multiplier: float
    direction: IMTPThresholdDirection
    dwell_samples: int
    search_start_index: int
    interpolation_method: RegistryReference = IMTP_NO_INTERPOLATION_METHOD

    def __post_init__(self) -> None:
        multiplier = _finite(self.sigma_multiplier, "sigma_multiplier")
        if multiplier != 5.0:
            raise ValueError("RES-66 V1 IMTP onset requires exactly 5.0 baseline SD")
        object.__setattr__(self, "sigma_multiplier", multiplier)
        _require_enum(self.direction, IMTPThresholdDirection, "direction")
        if self.direction is not IMTPThresholdDirection.ABOVE_THRESHOLD:
            raise ValueError("IMTP V1 onset requires an upward threshold crossing")
        if type(self.dwell_samples) is not int or self.dwell_samples < 1:
            raise ValueError("dwell_samples must be a positive integer")
        if type(self.search_start_index) is not int or self.search_start_index < 0:
            raise ValueError("search_start_index must be a non-negative integer")
        if self.interpolation_method != IMTP_NO_INTERPOLATION_METHOD:
            raise ValueError("IMTP V1 onset does not authorize interpolation")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPOnset:
    """Sample-attached IMTP onset with baseline and detector provenance."""

    occurrence_id: InstanceIdentifier
    source_context: ObservationContext
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_timebase: StrengthTimebase
    source_sample_count: int
    baseline_id: InstanceIdentifier
    baseline_segment: IMTPBaselineSegment
    baseline_mean_force_n: float
    baseline_standard_deviation_n: float
    threshold_n: float
    parameters: IMTPOnsetParameters
    sample_index: int
    event_time_s: float
    processing_run_id: InstanceIdentifier
    provenance: Provenance
    method: RegistryReference = IMTP_ONSET_BASELINE_FIVE_SD_METHOD
    event_definition: RegistryReference = IMTP_ONSET_EVENT_DEFINITION

    def __post_init__(self) -> None:
        if self.occurrence_id.instance_type != "event-occurrence":
            raise ValueError("IMTP onset occurrence must identify an event occurrence")
        for field_name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
            ("baseline_id", self.baseline_id, "imtp-baseline"),
        ):
            if value.instance_type != expected:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("onset source identity must identify a measurement")
        _require_instance(self.source_timebase, StrengthTimebase, "source_timebase")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("onset source_sample_count must be positive")
        _require_instance(self.parameters, IMTPOnsetParameters, "parameters")
        if self.method != IMTP_ONSET_BASELINE_FIVE_SD_METHOD:
            raise ValueError("IMTP onset method is not registered")
        if self.event_definition != IMTP_ONSET_EVENT_DEFINITION:
            raise ValueError("IMTP onset event definition is not registered")
        for field_name in (
            "baseline_mean_force_n",
            "baseline_standard_deviation_n",
            "threshold_n",
            "event_time_s",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        if self.baseline_standard_deviation_n < 0:
            raise ValueError("baseline standard deviation must be non-negative")
        if (
            self.threshold_n
            != self.baseline_mean_force_n + 5.0 * self.baseline_standard_deviation_n
        ):
            raise ValueError("onset threshold does not equal baseline mean plus five SD")
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise ValueError("onset sample index must be a non-negative integer")
        if self.processing_run_id.instance_type != "processing-run":
            raise ValueError("onset processing_run_id must identify a processing run")
        matching = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_entity_id == self.occurrence_id
        )
        if len(matching) != 1 or matching[0].processing_run_id != self.processing_run_id:
            raise ValueError("onset must preserve one producing processing run")
        if matching[0].method != IMTP_ONSET_BASELINE_FIVE_SD_METHOD:
            raise ValueError("onset processing run method is not the registered V1 method")


def _merge_provenance(left: Provenance, right: Provenance) -> Provenance:
    def unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
        result: list[T] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    return Provenance(
        provenance_id=left.provenance_id,
        source_artifacts=tuple(
            sorted(
                unique((*left.source_artifacts, *right.source_artifacts)),
                key=lambda item: item.artifact_id.qualified,
            )
        ),
        acquisitions=tuple(
            sorted(
                unique((*left.acquisitions, *right.acquisitions)),
                key=lambda item: item.acquisition_id.qualified,
            )
        ),
        processing_runs=tuple(
            sorted(
                unique((*left.processing_runs, *right.processing_runs)),
                key=lambda item: item.processing_run_id.qualified,
            )
        ),
        lineage_edges=tuple(
            sorted(
                unique((*left.lineage_edges, *right.lineage_edges)),
                key=lambda item: (item.from_id, item.to_id, item.relation.value),
            )
        ),
        evidence_references=unique((*left.evidence_references, *right.evidence_references)),
        metrological_traceability=unique(
            (*left.metrological_traceability, *right.metrological_traceability)
        ),
        recorded_at=left.recorded_at or right.recorded_at,
    )


def _provenance_with_run(
    base: Provenance,
    *,
    processing_run: ProcessingRun,
    output_entity_id: InstanceIdentifier,
    source_observation_ids: tuple[InstanceIdentifier, ...],
    source_acquisition_ids: tuple[InstanceIdentifier, ...],
    output_artifacts: tuple[SourceArtifact, ...] = (),
    supported_by: tuple[RegistryReference, ...] = (),
    evidence_references: tuple[EvidenceReference, ...] = (),
) -> Provenance:
    def unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
        result: list[T] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    artifacts = unique((*base.source_artifacts, *output_artifacts))
    runs = unique((*base.processing_runs, processing_run))
    evidence = unique((*base.evidence_references, *evidence_references))
    edges = list(base.lineage_edges)
    for source_id in source_observation_ids:
        edge = LineageEdge(
            source_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for artifact_id in processing_run.source_artifact_ids:
        edge = LineageEdge(
            artifact_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in edges:
            edges.append(edge)
    for acquisition_id in source_acquisition_ids:
        edge = LineageEdge(
            acquisition_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    for artifact in output_artifacts:
        edge = LineageEdge(
            processing_run.processing_run_id.qualified,
            artifact.artifact_id.qualified,
            LineageRelation.PRODUCED,
        )
        if edge not in edges:
            edges.append(edge)
    for reference in supported_by:
        edge = LineageEdge(
            reference.stable_id,
            processing_run.processing_run_id.qualified,
            LineageRelation.SUPPORTED_BY,
        )
        if edge not in edges:
            edges.append(edge)
    output_edge = LineageEdge(
        processing_run.processing_run_id.qualified,
        output_entity_id.qualified,
        LineageRelation.PRODUCED,
    )
    if output_edge not in edges:
        edges.append(output_edge)
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_entity_id.value),
        source_artifacts=artifacts,
        acquisitions=base.acquisitions,
        processing_runs=runs,
        lineage_edges=tuple(edges),
        evidence_references=evidence,
        metrological_traceability=base.metrological_traceability,
        recorded_at=base.recorded_at,
    )


def _validate_imtp_identity(identity: IMTPMeasurementIdentity) -> None:
    if not isinstance(identity, IMTPMeasurementIdentity):
        raise ValueError("IMTP operation requires IMTPMeasurementIdentity")
    if identity.semantic.test_family != IMTP_TEST_FAMILY:
        raise ValueError("IMTP identity must use the registered IMTP test family")
    protocol = identity.semantic.protocol_identity
    if protocol is not None and protocol.test_family.name != "IMTP":
        raise ValueError("IMTP protocol identity must use the IMTP family")


def _validate_force_input(force: IMTPForceInput, claim: str) -> RefusalResult | None:
    if not isinstance(force, IMTPForceInput):
        return _refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("typed IMTPForceInput",),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    try:
        _validate_imtp_identity(force.identity)
        if (
            force.identity.semantic.construct != IMTP_CONSTRUCT
            or force.identity.semantic.measurand != IMTP_VERTICAL_FORCE_MEASURAND
            or force.identity.semantic.metric_definition != IMTP_FORCE_TIME_SERIES_METRIC
        ):
            raise ValueError("IMTP source semantic identity is not the registered force series")
        if force.observation.identity != force.identity:
            raise ValueError("observation and supplied IMTP identity differ")
        if (
            force.identity.semantic.protocol_identity is None
            or force.identity.semantic.protocol != IMTP_PROTOCOL_V1
        ):
            raise ValueError("complete IMTP protocol identity is required")
        protocol = force.identity.semantic.protocol_identity
        if protocol is None:
            raise ValueError("IMTP protocol identity is unresolved")
        if (
            protocol.device_or_system is not None
            and protocol.device_or_system != force.identity.acquisition.device
        ):
            raise ValueError("IMTP protocol device does not match acquisition device")
        if (
            protocol.provider is not None
            and protocol.provider != force.identity.acquisition.provider
        ):
            raise ValueError("IMTP protocol provider does not match acquisition provider")
        if (
            protocol.sensor_modality is not StrengthSensorModality.UNKNOWN
            and protocol.sensor_modality != force.identity.acquisition.sensor_modality
        ):
            raise ValueError("IMTP protocol sensor modality does not match acquisition")
        if (
            protocol.attachment_location is not None
            and protocol.attachment_location != force.identity.acquisition.attachment_location
        ):
            raise ValueError("IMTP protocol attachment does not match acquisition")
        if (
            protocol.sampling is not None
            and protocol.sampling != force.identity.acquisition.sampling
        ):
            raise ValueError("IMTP protocol sampling does not match acquisition")
        if force.identity.processing.registered_operation != IMTP_INPUT_OPERATION:
            raise ValueError("IMTP source operation is not registered")
        if force.identity.version.processing_method != IMTP_INPUT_OPERATION:
            raise ValueError("IMTP source version does not name its registered operation")
        if force.series.source_measurement_identity_id != force.identity.identity_id:
            raise ValueError("series measurement identity does not match force identity")
        if force.series.source_artifact_id != force.source_artifact.artifact_id:
            raise ValueError("series artifact does not match source artifact")
        if force.source_artifact.status is not StrengthArtifactStatus.VERIFIED:
            raise ValueError("source artifact is not verified")
        if not force.source_artifact.immutable:
            raise ValueError("source artifact is not immutable")
        if force.source_artifact.content_digest != force.series.canonical_content_digest():
            raise ValueError("source artifact digest does not match force samples")
        acquisition = force.identity.acquisition
        if acquisition.raw_artifact != force.source_artifact.artifact_id:
            raise ValueError("identity raw artifact does not match source artifact")
        if acquisition.acquisition_instance_id != force.acquisition.acquisition_id:
            raise ValueError("identity acquisition ID does not match acquisition record")
        if force.acquisition.source_artifact_id != force.source_artifact.artifact_id:
            raise ValueError("acquisition record does not match source artifact")
        if force.acquisition.acquisition_id != force.series.acquisition_id:
            raise ValueError("series acquisition ID does not match acquisition record")
        if force.acquisition.sampling != acquisition.sampling:
            raise ValueError("IMTP acquisition sampling does not match identity")
        if (
            force.acquisition.device != acquisition.device
            or acquisition.device != force.identity.acquisition.device
        ):
            raise ValueError("IMTP acquisition device does not match identity")
        if acquisition.timebase != force.series.timebase:
            raise ValueError("identity timebase does not match force series")
        if acquisition.unit != force.series.unit or force.series.unit != NEWTON:
            raise ValueError("IMTP force source must use the registered N unit")
        if acquisition.physical_axis != force.series.physical_axis:
            raise ValueError("identity physical axis does not match force series")
        if acquisition.reference_frame != force.series.reference_frame:
            raise ValueError("identity reference frame does not match force series")
        if acquisition.sign_convention != force.series.sign_convention:
            raise ValueError("identity sign convention does not match force series")
        if force.series.processing_state is StrengthProcessingState.UNKNOWN:
            raise ValueError("IMTP source processing state is unknown")
        if acquisition.processing_state != force.series.processing_state:
            raise ValueError("identity processing state does not match force series")
        if force.identity.processing.processing_state != force.series.processing_state:
            raise ValueError("IMTP processing identity state does not match force series")
        if force.identity.acquisition.sampling is None:
            raise ValueError("IMTP source sampling metadata is required")
        if (
            force.series.timebase.kind is StrengthTimebaseKind.REGULAR
            and force.identity.acquisition.sampling.frequency_hz is not None
            and force.identity.acquisition.sampling.frequency_hz
            != force.series.timebase.sample_rate_hz
        ):
            raise ValueError("IMTP sampling frequency does not match regular timebase")
        if (
            force.series.physical_axis is None
            or force.series.reference_frame is None
            or force.series.sign_convention is None
        ):
            raise ValueError("IMTP source axis, frame, and sign metadata are required")
        if force.observation.context is None:
            raise ValueError("IMTP observation context is missing")
        if not isinstance(force.observation.result.value, StructuredOutputReference):
            raise ValueError("IMTP source result must reference the series artifact")
        reference = force.observation.result.value
        if (
            reference.artifact_id != force.source_artifact.artifact_id
            or reference.schema != IMTP_FORCE_TIME_SERIES_SCHEMA
        ):
            raise ValueError("IMTP source result reference is not bound to the series")
        if force.observation.result.status is not ResultStatus.VALID:
            raise ValueError("IMTP source result is not valid")
        if force.observation.result.classification.value_origin != _source_origin(
            force.series.processing_state
        ):
            raise ValueError("IMTP source result has an invalid value origin")
        artifact_ids = {item.artifact_id for item in force.observation.provenance.source_artifacts}
        acquisition_ids = {
            item.acquisition_id for item in force.observation.provenance.acquisitions
        }
        if (
            force.source_artifact.artifact_id not in artifact_ids
            or force.acquisition.acquisition_id not in acquisition_ids
        ):
            raise ValueError("IMTP source provenance omits artifact or acquisition")
        matching_artifacts = tuple(
            artifact
            for artifact in force.observation.provenance.source_artifacts
            if artifact.artifact_id == force.source_artifact.artifact_id
        )
        matching_acquisitions = tuple(
            acquisition_record
            for acquisition_record in force.observation.provenance.acquisitions
            if acquisition_record.acquisition_id == force.acquisition.acquisition_id
        )
        if matching_artifacts != (force.source_artifact,) or matching_acquisitions != (
            force.acquisition,
        ):
            raise ValueError("IMTP source provenance objects do not match bound inputs")
        if not any(
            edge.from_id == force.source_artifact.artifact_id.qualified
            and edge.to_id == force.acquisition.acquisition_id.qualified
            and edge.relation is LineageRelation.ACQUIRED_AS
            for edge in force.observation.provenance.lineage_edges
        ):
            raise ValueError("IMTP provenance omits artifact-to-acquisition edge")
        if not any(
            edge.from_id == force.acquisition.acquisition_id.qualified
            and edge.to_id == force.observation.observation_id.qualified
            and edge.relation is LineageRelation.PRODUCED
            for edge in force.observation.provenance.lineage_edges
        ):
            raise ValueError("IMTP provenance omits source observation edge")
        if not any(
            edge.from_id == force.series.signal_id.qualified
            and edge.to_id == force.observation.observation_id.qualified
            and edge.relation is LineageRelation.PRODUCED
            for edge in force.observation.provenance.lineage_edges
        ):
            raise ValueError("IMTP provenance omits source-series edge")
    except (AttributeError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"complete typed IMTP force source: {exc}",),
            (force.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def _baseline_values(force: IMTPForceInput, segment: IMTPBaselineSegment) -> tuple[float, ...]:
    if (
        segment.source_signal_id != force.series.signal_id
        or segment.source_artifact_id != force.source_artifact.artifact_id
        or segment.source_measurement_identity_id != force.identity.identity_id
    ):
        raise ValueError("baseline segment is not linked to the exact force source")
    if segment.end_index > len(force.series.samples):
        raise ValueError("baseline segment exceeds force source support")
    return force.series.samples[segment.start_index : segment.end_index]


def build_imtp_baseline(
    force: IMTPForceInput,
    segment: IMTPBaselineSegment,
    *,
    output_baseline_id: InstanceIdentifier | None = None,
) -> IMTPBaseline | RefusalResult:
    """Compute sample mean and sample SD over an explicit half-open baseline."""

    claim = "build IMTP baseline force statistics"
    source_refusal = _validate_force_input(force, claim)
    if source_refusal is not None:
        return source_refusal
    try:
        values = _baseline_values(force, segment)
        if len(values) < 2:
            raise ValueError("baseline requires at least two samples")
        mean_force = math.fsum(values) / len(values)
        standard_deviation = stdev(values)
        start_time = time_at(force.series.timebase, segment.start_index)
        end_time = time_at(force.series.timebase, segment.end_index - 1)
        qc = IMTPBaselineQC(
            sample_count=len(values),
            elapsed_sample_span_s=end_time - start_time,
            mean_force_n=mean_force,
            standard_deviation_n=standard_deviation,
            range_n=max(values) - min(values),
        )
    except (IndexError, OverflowError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.BASELINE_QC_REQUIRED,),
            (f"deterministic baseline statistics: {exc}",),
            (force.observation.observation_id,),
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    digest = canonical_hash(
        {
            "operation": IMTP_BASELINE_OPERATION.stable_id,
            "source_observation_id": force.observation.observation_id.qualified,
            "segment": segment,
        }
    ).removeprefix("sha256:")[:24]
    baseline_id = output_baseline_id or InstanceIdentifier("imtp-baseline", f"res66:{digest}")
    if baseline_id.instance_type != "imtp-baseline":
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("output_baseline_id must identify an IMTP baseline",),
            (force.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = (
        MetadataEntry("operation_id", IMTP_BASELINE_OPERATION.stable_id),
        MetadataEntry("source_observation_id", force.observation.observation_id.qualified),
        MetadataEntry("source_signal_id", force.series.signal_id.qualified),
        MetadataEntry("source_artifact_id", force.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", force.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", force.identity.identity_id.stable_id),
        MetadataEntry("segment", canonical_json(segment)),
        MetadataEntry("mean_force_n", qc.mean_force_n),
        MetadataEntry("standard_deviation_n", qc.standard_deviation_n),
        MetadataEntry("standard_deviation_method", "SAMPLE_STANDARD_DEVIATION_N_MINUS_1"),
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"imtp-baseline:{digest}"),
        source_artifact_ids=(force.source_artifact.artifact_id,),
        method=IMTP_BASELINE_OPERATION,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=baseline_id,
    )
    provenance = _provenance_with_run(
        force.observation.provenance,
        processing_run=run,
        output_entity_id=baseline_id,
        source_observation_ids=(force.observation.observation_id,),
        source_acquisition_ids=(force.acquisition.acquisition_id,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        evidence_references=(
            EvidenceReference(RES66_DECISION_STRENGTH_IMTP_VBT, "registered IMTP baseline method"),
        ),
    )
    return IMTPBaseline(
        baseline_id=baseline_id,
        source_context=force.observation.context,
        source_observation_id=force.observation.observation_id,
        source_signal_id=force.series.signal_id,
        source_artifact_id=force.source_artifact.artifact_id,
        source_acquisition_id=force.acquisition.acquisition_id,
        source_measurement_identity_id=force.identity.identity_id,
        segment=segment,
        qc=qc,
        processing_run_id=run.processing_run_id,
        provenance=provenance,
    )


def _validate_baseline_for_force(force: IMTPForceInput, baseline: IMTPBaseline) -> None:
    if not isinstance(baseline, IMTPBaseline):
        raise ValueError("IMTP operation requires a qualified IMTPBaseline")
    if (
        baseline.source_context != force.observation.context
        or baseline.source_observation_id != force.observation.observation_id
        or baseline.source_signal_id != force.series.signal_id
        or baseline.source_artifact_id != force.source_artifact.artifact_id
        or baseline.source_acquisition_id != force.acquisition.acquisition_id
        or baseline.source_measurement_identity_id != force.identity.identity_id
    ):
        raise ValueError("baseline is not from the exact IMTP force context/source")
    if tuple(
        artifact
        for artifact in baseline.provenance.source_artifacts
        if artifact.artifact_id == force.source_artifact.artifact_id
    ) != (force.source_artifact,):
        raise ValueError("baseline provenance does not preserve the force artifact")
    if tuple(
        acquisition
        for acquisition in baseline.provenance.acquisitions
        if acquisition.acquisition_id == force.acquisition.acquisition_id
    ) != (force.acquisition,):
        raise ValueError("baseline provenance does not preserve the force acquisition")
    values = _baseline_values(force, baseline.segment)
    if len(values) != baseline.qc.sample_count:
        raise ValueError("baseline sample count does not match source segment")
    mean_force = math.fsum(values) / len(values)
    sd = stdev(values)
    if mean_force != baseline.qc.mean_force_n or sd != baseline.qc.standard_deviation_n:
        raise ValueError("baseline statistics do not reproduce from the source samples")


def detect_imtp_onset(
    force: IMTPForceInput,
    baseline: IMTPBaseline,
    parameters: IMTPOnsetParameters,
    *,
    output_occurrence_id: InstanceIdentifier | None = None,
) -> IMTPOnset | RefusalResult:
    """Detect the first strict upward crossing of baseline mean + five SD."""

    claim = "detect IMTP force onset"
    source_refusal = _validate_force_input(force, claim)
    if source_refusal is not None:
        return source_refusal
    try:
        _validate_baseline_for_force(force, baseline)
        if parameters.search_start_index < baseline.segment.end_index:
            raise ValueError("onset search must begin after the half-open baseline")
        if parameters.search_start_index >= len(force.series.samples):
            raise ValueError("onset search must be inside force source support")
        threshold = baseline.qc.mean_force_n + 5.0 * baseline.qc.standard_deviation_n
        runs: list[tuple[int, int]] = []
        index = parameters.search_start_index
        while index < len(force.series.samples):
            if force.series.samples[index] <= threshold:
                index += 1
                continue
            start = index
            index += 1
            while index < len(force.series.samples) and force.series.samples[index] > threshold:
                index += 1
            if index - start >= parameters.dwell_samples:
                runs.append((start, index))
        if not runs:
            reason = RefusalReasonCode.INSUFFICIENT_DWELL
            if all(
                value <= threshold
                for value in force.series.samples[parameters.search_start_index :]
            ):
                reason = RefusalReasonCode.THRESHOLD_NOT_CROSSED
            return _refusal(
                claim,
                (reason,),
                ("a qualifying strict upward baseline-plus-five-SD crossing",),
                (force.observation.observation_id, baseline.baseline_id),
            )
        sample_index = runs[0][0]
        threshold = float(threshold)
        event_time = time_at(force.series.timebase, sample_index)
    except (IndexError, OverflowError, TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            (f"qualified onset parameters and baseline: {exc}",),
            tuple(
                item
                for item in (
                    force.observation.observation_id,
                    baseline.baseline_id if isinstance(baseline, IMTPBaseline) else None,
                )
                if item is not None
            ),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    digest = canonical_hash(
        {
            "method": IMTP_ONSET_BASELINE_FIVE_SD_METHOD,
            "source_observation_id": force.observation.observation_id,
            "baseline_id": baseline.baseline_id,
            "parameters": parameters,
            "sample_index": sample_index,
        }
    ).removeprefix("sha256:")[:24]
    occurrence_id = output_occurrence_id or InstanceIdentifier(
        "event-occurrence", f"imtp-onset:{digest}"
    )
    if occurrence_id.instance_type != "event-occurrence":
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("output_occurrence_id must identify an event occurrence",),
            (force.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    run_parameters = (
        MetadataEntry("method_id", IMTP_ONSET_BASELINE_FIVE_SD_METHOD.stable_id),
        MetadataEntry("event_definition", IMTP_ONSET_EVENT_DEFINITION.stable_id),
        MetadataEntry("baseline_id", baseline.baseline_id.qualified),
        MetadataEntry("baseline_segment", canonical_json(baseline.segment)),
        MetadataEntry("baseline_mean_force_n", baseline.qc.mean_force_n),
        MetadataEntry("baseline_standard_deviation_n", baseline.qc.standard_deviation_n),
        MetadataEntry("sigma_multiplier", parameters.sigma_multiplier),
        MetadataEntry("direction", parameters.direction.value),
        MetadataEntry("dwell_samples", parameters.dwell_samples),
        MetadataEntry("search_start_index", parameters.search_start_index),
        MetadataEntry("interpolation", parameters.interpolation_method.stable_id),
        MetadataEntry("selected_sample_index", sample_index),
        MetadataEntry("event_time_s", event_time),
        MetadataEntry("effective_threshold_n", threshold),
        MetadataEntry("source_observation_id", force.observation.observation_id.qualified),
        MetadataEntry("source_signal_id", force.series.signal_id.qualified),
        MetadataEntry("source_artifact_id", force.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", force.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", force.identity.identity_id.stable_id),
        MetadataEntry("source_timebase", canonical_json(force.series.timebase)),
        MetadataEntry("source_sample_count", len(force.series.samples)),
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"imtp-onset:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                {
                    artifact.artifact_id
                    for artifact in (
                        *force.observation.provenance.source_artifacts,
                        *baseline.provenance.source_artifacts,
                    )
                },
                key=lambda item: item.qualified,
            )
        ),
        method=IMTP_ONSET_BASELINE_FIVE_SD_METHOD,
        parameters=run_parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=occurrence_id,
    )
    base = _merge_provenance(force.observation.provenance, baseline.provenance)
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=occurrence_id,
        source_observation_ids=(force.observation.observation_id, baseline.baseline_id),
        source_acquisition_ids=(force.acquisition.acquisition_id,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        evidence_references=(
            EvidenceReference(RES66_DECISION_STRENGTH_IMTP_VBT, "registered five-SD onset"),
        ),
    )
    return IMTPOnset(
        occurrence_id=occurrence_id,
        source_context=force.observation.context,
        source_observation_id=force.observation.observation_id,
        source_signal_id=force.series.signal_id,
        source_artifact_id=force.source_artifact.artifact_id,
        source_acquisition_id=force.acquisition.acquisition_id,
        source_measurement_identity_id=force.identity.identity_id,
        source_timebase=force.series.timebase,
        source_sample_count=len(force.series.samples),
        baseline_id=baseline.baseline_id,
        baseline_segment=baseline.segment,
        baseline_mean_force_n=baseline.qc.mean_force_n,
        baseline_standard_deviation_n=baseline.qc.standard_deviation_n,
        threshold_n=threshold,
        parameters=parameters,
        sample_index=sample_index,
        event_time_s=event_time,
        processing_run_id=run.processing_run_id,
        provenance=provenance,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPMetricSupport:
    """Exact inclusive source support used by one IMTP metric."""

    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    source_timebase: StrengthTimebase
    source_sample_count: int
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float
    onset: IMTPOnset
    trial_end_rule: RegistryReference = IMTP_TRIAL_SUPPORT_METHOD

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_signal_id", self.source_signal_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("source_acquisition_id", self.source_acquisition_id, "acquisition"),
        ):
            if value.instance_type != expected:
                raise ValueError(f"{field_name} has the wrong identifier type")
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("support source identity must identify a measurement")
        if type(self.source_sample_count) is not int or self.source_sample_count < 1:
            raise ValueError("support source_sample_count must be positive")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("support indices must be integers")
        if (
            self.start_index < 0
            or self.end_index < self.start_index
            or self.end_index >= self.source_sample_count
        ):
            raise ValueError("support must be a non-empty inclusive interval")
        if self.trial_end_rule != IMTP_TRIAL_SUPPORT_METHOD:
            raise ValueError("support trial-end rule is not registered")
        expected_start = time_at(self.source_timebase, self.start_index)
        expected_end = time_at(self.source_timebase, self.end_index)
        if self.start_time_s != expected_start or self.end_time_s != expected_end:
            raise ValueError("support times must equal exact source sample times")
        if self.onset.occurrence_id.instance_type != "event-occurrence":
            raise ValueError("support onset must be an event occurrence")
        if (
            self.onset.source_observation_id != self.source_observation_id
            or self.onset.source_signal_id != self.source_signal_id
            or self.onset.source_artifact_id != self.source_artifact_id
            or self.onset.source_acquisition_id != self.source_acquisition_id
            or self.onset.source_measurement_identity_id != self.source_measurement_identity_id
            or self.onset.source_timebase != self.source_timebase
            or self.onset.source_sample_count != self.source_sample_count
            or self.onset.sample_index != self.start_index
        ):
            raise ValueError("support is not bound to the exact onset source")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPMetricResult:
    """One registered IMTP peak, time-specific force, impulse, or RFD result."""

    observation: ScientificMeasurementObservation
    metric: IMTPMetric
    force_input: IMTPForceInput
    onset: IMTPOnset
    support: IMTPMetricSupport
    force_quantity: IMTPForceQuantity
    window_ms: int | None = None

    def __post_init__(self) -> None:
        _validate_imtp_metric_result(self)

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)

    @property
    def value_n(self) -> float:
        return self.value

    @property
    def method_identity_key(self) -> object:
        return _metric_method_key(self)


def _validate_onset_for_force(force: IMTPForceInput, onset: IMTPOnset) -> None:
    if not isinstance(onset, IMTPOnset):
        raise ValueError("IMTP metric requires an IMTP onset")
    if (
        onset.source_context != force.observation.context
        or onset.source_observation_id != force.observation.observation_id
        or onset.source_signal_id != force.series.signal_id
        or onset.source_artifact_id != force.source_artifact.artifact_id
        or onset.source_acquisition_id != force.acquisition.acquisition_id
        or onset.source_measurement_identity_id != force.identity.identity_id
        or onset.source_timebase != force.series.timebase
        or onset.source_sample_count != len(force.series.samples)
        or onset.baseline_segment.source_signal_id != force.series.signal_id
        or onset.baseline_segment.source_artifact_id != force.source_artifact.artifact_id
        or onset.baseline_segment.source_measurement_identity_id != force.identity.identity_id
    ):
        raise ValueError("IMTP onset is not from the exact force context/source")
    if onset.sample_index >= len(force.series.samples):
        raise ValueError("IMTP onset sample is outside source support")
    if time_at(force.series.timebase, onset.sample_index) != onset.event_time_s:
        raise ValueError("IMTP onset time does not match source timebase")
    threshold = onset.baseline_mean_force_n + 5.0 * onset.baseline_standard_deviation_n
    if onset.threshold_n != threshold:
        raise ValueError("IMTP onset threshold does not reproduce")
    if force.series.samples[onset.sample_index] <= threshold:
        raise ValueError("IMTP onset sample no longer crosses its threshold")
    if onset.parameters.search_start_index > onset.sample_index:
        raise ValueError("IMTP onset precedes its declared search start")
    if onset.baseline_segment.end_index > onset.parameters.search_start_index:
        raise ValueError("IMTP onset search does not follow the baseline")
    baseline_values = _baseline_values(force, onset.baseline_segment)
    if (
        math.fsum(baseline_values) / len(baseline_values) != onset.baseline_mean_force_n
        or stdev(baseline_values) != onset.baseline_standard_deviation_n
    ):
        raise ValueError("IMTP onset baseline statistics do not reproduce from the source")
    runs_start = onset.parameters.search_start_index
    previous_crossing = False
    for index in range(runs_start, onset.sample_index):
        if force.series.samples[index] > threshold:
            previous_crossing = True
            break
    if previous_crossing:
        raise ValueError("IMTP onset is not the first qualifying crossing")
    run_end = onset.sample_index
    while run_end < len(force.series.samples) and force.series.samples[run_end] > threshold:
        run_end += 1
    if run_end - onset.sample_index < onset.parameters.dwell_samples:
        raise ValueError("IMTP onset no longer satisfies its dwell")
    matching_runs = tuple(
        run
        for run in onset.provenance.processing_runs
        if run.output_entity_id == onset.occurrence_id
    )
    if len(matching_runs) != 1:
        raise ValueError("IMTP onset provenance must preserve one producing run")
    run = matching_runs[0]
    expected_parameters = (
        MetadataEntry("method_id", IMTP_ONSET_BASELINE_FIVE_SD_METHOD.stable_id),
        MetadataEntry("event_definition", IMTP_ONSET_EVENT_DEFINITION.stable_id),
        MetadataEntry("baseline_id", onset.baseline_id.qualified),
        MetadataEntry("baseline_segment", canonical_json(onset.baseline_segment)),
        MetadataEntry("baseline_mean_force_n", onset.baseline_mean_force_n),
        MetadataEntry("baseline_standard_deviation_n", onset.baseline_standard_deviation_n),
        MetadataEntry("sigma_multiplier", onset.parameters.sigma_multiplier),
        MetadataEntry("direction", onset.parameters.direction.value),
        MetadataEntry("dwell_samples", onset.parameters.dwell_samples),
        MetadataEntry("search_start_index", onset.parameters.search_start_index),
        MetadataEntry("interpolation", onset.parameters.interpolation_method.stable_id),
        MetadataEntry("selected_sample_index", onset.sample_index),
        MetadataEntry("event_time_s", onset.event_time_s),
        MetadataEntry("effective_threshold_n", onset.threshold_n),
        MetadataEntry("source_observation_id", force.observation.observation_id.qualified),
        MetadataEntry("source_signal_id", force.series.signal_id.qualified),
        MetadataEntry("source_artifact_id", force.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", force.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", force.identity.identity_id.stable_id),
        MetadataEntry("source_timebase", canonical_json(force.series.timebase)),
        MetadataEntry("source_sample_count", len(force.series.samples)),
    )
    if (
        run.method != IMTP_ONSET_BASELINE_FIVE_SD_METHOD
        or run.software_version != RES66_SOFTWARE_VERSION
        or run.parameters != expected_parameters
        or force.source_artifact.artifact_id not in run.source_artifact_ids
    ):
        raise ValueError("IMTP onset processing run does not preserve its method parameters")


def _make_support(
    force: IMTPForceInput,
    onset: IMTPOnset,
    *,
    end_index: int,
) -> IMTPMetricSupport:
    if end_index < onset.sample_index or end_index >= len(force.series.samples):
        raise ValueError("IMTP metric end index must be inside onset-to-trial support")
    return IMTPMetricSupport(
        source_observation_id=force.observation.observation_id,
        source_signal_id=force.series.signal_id,
        source_artifact_id=force.source_artifact.artifact_id,
        source_acquisition_id=force.acquisition.acquisition_id,
        source_measurement_identity_id=force.identity.identity_id,
        source_timebase=force.series.timebase,
        source_sample_count=len(force.series.samples),
        start_index=onset.sample_index,
        end_index=end_index,
        start_time_s=time_at(force.series.timebase, onset.sample_index),
        end_time_s=time_at(force.series.timebase, end_index),
        onset=onset,
    )


def _required_window(window_ms: int) -> int:
    if type(window_ms) is not int or window_ms not in _ALLOWED_WINDOWS_MS:
        raise ValueError("IMTP window must be one of 50, 100, 150, or 200 ms")
    return window_ms


def _exact_index_for_window(
    force: IMTPForceInput,
    onset: IMTPOnset,
    window_ms: int,
) -> int | None:
    seconds = window_ms / 1000.0
    if force.series.timebase.kind is StrengthTimebaseKind.REGULAR:
        rate = force.series.timebase.sample_rate_hz
        if rate is None:
            return None
        raw_offset = seconds * rate
        rounded = round(raw_offset)
        if not math.isclose(raw_offset, rounded, rel_tol=0.0, abs_tol=1e-12):
            return None
        index = onset.sample_index + rounded
        if index >= len(force.series.samples):
            return None
        if not math.isclose(
            time_at(force.series.timebase, index) - onset.event_time_s,
            seconds,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return None
        return index
    target_time = onset.event_time_s + seconds
    for index in range(onset.sample_index + 1, len(force.series.samples)):
        if force.series.timebase.times_s[index] == target_time:
            return index
    return None


def _force_value_at(
    force: IMTPForceInput, index: int, quantity: IMTPForceQuantity, onset: IMTPOnset
) -> float:
    value = force.series.samples[index]
    if quantity is IMTPForceQuantity.GROSS_VERTICAL_FORCE:
        return value
    if quantity is IMTPForceQuantity.NET_FORCE_ABOVE_BASELINE:
        return value - onset.baseline_mean_force_n
    raise ValueError("IMTP force quantity is not registered")


def _metric_reference(
    metric: IMTPMetric,
    quantity: IMTPForceQuantity,
    window_ms: int | None,
) -> tuple[RegistryReference, RegistryReference, UnitReference, str]:
    if metric is IMTPMetric.PEAK_FORCE:
        return (
            IMTP_GROSS_PEAK_FORCE_METRIC
            if quantity is IMTPForceQuantity.GROSS_VERTICAL_FORCE
            else IMTP_NET_PEAK_FORCE_METRIC,
            IMTP_SAMPLE_PEAK_FORCE_OPERATION,
            NEWTON,
            "SAMPLE_MAXIMUM_OVER_ONSET_TO_TRIAL_END",
        )
    if metric is IMTPMetric.FORCE_AT_TIME:
        if window_ms not in _ALLOWED_WINDOWS_MS:
            raise ValueError("force-at-time window is not registered")
        return (
            {
                50: IMTP_FORCE_AT_50_MS_METRIC,
                100: IMTP_FORCE_AT_100_MS_METRIC,
                150: IMTP_FORCE_AT_150_MS_METRIC,
                200: IMTP_FORCE_AT_200_MS_METRIC,
            }[window_ms],
            IMTP_FORCE_AT_TIME_OPERATION,
            NEWTON,
            "EXACT_SOURCE_SAMPLE_AT_ONSET_PLUS_REGISTERED_TIME",
        )
    if metric is IMTPMetric.IMPULSE:
        if window_ms not in _ALLOWED_WINDOWS_MS:
            raise ValueError("impulse window is not registered")
        return (
            {
                50: IMTP_IMPULSE_0_50_MS_METRIC,
                100: IMTP_IMPULSE_0_100_MS_METRIC,
                150: IMTP_IMPULSE_0_150_MS_METRIC,
                200: IMTP_IMPULSE_0_200_MS_METRIC,
            }[window_ms],
            IMTP_IMPULSE_OPERATION,
            NEWTON_SECOND,
            "TRAPEZOIDAL_INTEGRAL_OVER_EXACT_ONSET_INTERVAL",
        )
    if metric is IMTPMetric.RFD:
        if window_ms not in _ALLOWED_WINDOWS_MS:
            raise ValueError("RFD window is not registered")
        return (
            {
                50: IMTP_RFD_0_50_MS_METRIC,
                100: IMTP_RFD_0_100_MS_METRIC,
                150: IMTP_RFD_0_150_MS_METRIC,
                200: IMTP_RFD_0_200_MS_METRIC,
            }[window_ms],
            IMTP_RFD_OPERATION,
            NEWTON_PER_SECOND,
            "ENDPOINT_FORCE_DIFFERENCE_DIVIDED_BY_EXACT_DURATION",
        )
    raise ValueError("IMTP metric is not registered")


@dataclass(frozen=True, slots=True)
class _MetricCalculationInput:
    force_input: IMTPForceInput
    onset: IMTPOnset
    support: IMTPMetricSupport
    metric: IMTPMetric
    force_quantity: IMTPForceQuantity
    window_ms: int | None


def _expected_metric_value(result: IMTPMetricResult | _MetricCalculationInput) -> float:
    force = result.force_input
    support = result.support
    if result.metric is IMTPMetric.PEAK_FORCE:
        return max(
            _force_value_at(force, index, result.force_quantity, result.onset)
            for index in range(support.start_index, support.end_index + 1)
        )
    if result.metric is IMTPMetric.FORCE_AT_TIME:
        if result.window_ms is None:
            raise ValueError("force-at-time result requires a window")
        index = _exact_index_for_window(force, result.onset, result.window_ms)
        if index is None or index != support.end_index:
            raise ValueError("force-at-time support is not an exact registered sample")
        return _force_value_at(force, index, result.force_quantity, result.onset)
    values = tuple(
        _force_value_at(force, index, result.force_quantity, result.onset)
        for index in range(support.start_index, support.end_index + 1)
    )
    if support.end_index == support.start_index:
        raise ValueError("IMTP interval metrics require at least one time interval")
    area = math.fsum(
        0.5
        * (values[offset - 1] + values[offset])
        * (
            time_at(force.series.timebase, support.start_index + offset)
            - time_at(force.series.timebase, support.start_index + offset - 1)
        )
        for offset in range(1, len(values))
    )
    duration = support.end_time_s - support.start_time_s
    if duration <= 0 or not math.isfinite(duration):
        raise ValueError("IMTP interval must have a positive duration")
    if result.metric is IMTPMetric.IMPULSE:
        return area
    if result.metric is IMTPMetric.RFD:
        return (values[-1] - values[0]) / duration
    raise ValueError("IMTP metric is not registered")


def _metric_method_key(result: IMTPMetricResult) -> object:
    metric_reference, operation, unit, equation = _metric_reference(
        result.metric, result.force_quantity, result.window_ms
    )
    identity = result.force_input.identity
    acquisition = identity.acquisition
    acquisition_method = replace(
        acquisition,
        raw_artifact=None,
        acquisition_instance_id=None,
    )
    source_timebase = result.force_input.series.timebase
    timebase_method: object
    if source_timebase.kind is StrengthTimebaseKind.REGULAR:
        timebase_method = (source_timebase.kind, source_timebase.sample_rate_hz)
    else:
        timebase_method = (
            source_timebase.kind,
            tuple(right - left for left, right in pairwise(source_timebase.times_s)),
        )
    return {
        "metric": metric_reference,
        "operation": operation,
        "unit": unit,
        "force_quantity": result.force_quantity,
        "window_ms": result.window_ms,
        "equation": equation,
        "protocol": identity.semantic.protocol_identity,
        "acquisition": acquisition_method,
        "source_processing_state": result.force_input.series.processing_state,
        "filtering": identity.processing.filtering,
        "filtering_status": identity.processing.filtering_status,
        "smoothing": identity.processing.smoothing,
        "resampling": identity.processing.resampling,
        "timebase": timebase_method,
        "onset_method": IMTP_ONSET_BASELINE_FIVE_SD_METHOD,
        "onset_parameters": result.onset.parameters,
        "trial_end_rule": result.support.trial_end_rule,
    }


def _require_metric_lineage(
    observation: ScientificMeasurementObservation,
    *,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    entity_ids: tuple[InstanceIdentifier, ...],
) -> None:
    identity = observation.identity
    if not isinstance(identity, IMTPMeasurementIdentity):
        raise ValueError("IMTP output requires IMTP measurement identity")
    if (
        identity.processing.registered_operation != operation
        or identity.version.processing_method != operation
        or identity.version.method_registry_version != STRENGTH_REGISTRY_VERSION
        or identity.version.software_version != RES66_SOFTWARE_VERSION
    ):
        raise ValueError("IMTP output operation identity is not registered")
    if identity.processing.method_parameters != parameters:
        raise ValueError("IMTP output processing parameters are not preserved")
    if observation.result.status is not ResultStatus.VALID:
        raise ValueError("IMTP output result must be valid")
    if (
        observation.result.classification.value_origin
        is not ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    ):
        raise ValueError("IMTP output must be a derived mechanical quantity")
    if observation.result.classification.scientific_roles:
        raise ValueError("IMTP output must not carry an interpretive role")
    runs = tuple(
        run
        for run in observation.provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(runs) != 1 or runs[0].method != operation or runs[0].parameters != parameters:
        raise ValueError("IMTP output must preserve one matching processing run")
    if any(
        artifact_id
        not in tuple(artifact.artifact_id for artifact in observation.provenance.source_artifacts)
        for artifact_id in runs[0].source_artifact_ids
    ):
        raise ValueError("IMTP output processing run names an absent source artifact")
    run_id = runs[0].processing_run_id.qualified
    for entity_id in entity_ids:
        if not any(
            edge.from_id == entity_id.qualified
            and edge.to_id == run_id
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in observation.provenance.lineage_edges
        ):
            raise ValueError("IMTP output is missing exact source lineage")


def _validate_imtp_metric_result(result: IMTPMetricResult) -> None:
    source_refusal = _validate_force_input(result.force_input, "validate IMTP metric result")
    if source_refusal is not None:
        raise ValueError(source_refusal.blocked_claim)
    _validate_onset_for_force(result.force_input, result.onset)
    if result.support.onset != result.onset:
        raise ValueError("IMTP metric support onset does not match metric onset")
    if (
        result.support.source_observation_id != result.force_input.observation.observation_id
        or result.support.source_signal_id != result.force_input.series.signal_id
        or result.support.source_artifact_id != result.force_input.source_artifact.artifact_id
        or result.support.source_acquisition_id != result.force_input.acquisition.acquisition_id
        or result.support.source_measurement_identity_id != result.force_input.identity.identity_id
        or result.support.source_sample_count != len(result.force_input.series.samples)
        or result.support.source_timebase != result.force_input.series.timebase
    ):
        raise ValueError("IMTP metric support is not bound to the exact force input")
    if result.metric is IMTPMetric.FORCE_AT_TIME and result.window_ms not in _ALLOWED_WINDOWS_MS:
        raise ValueError("IMTP force-at-time metric requires a registered window")
    if (
        result.metric in {IMTPMetric.IMPULSE, IMTPMetric.RFD}
        and result.window_ms not in _ALLOWED_WINDOWS_MS
    ):
        raise ValueError("IMTP interval metric requires a registered window")
    if result.metric in {IMTPMetric.IMPULSE, IMTPMetric.RFD}:
        if result.window_ms is None:
            raise ValueError("IMTP interval metric requires a window")
        expected_end = _exact_index_for_window(result.force_input, result.onset, result.window_ms)
        if expected_end is None or result.support.end_index != expected_end:
            raise ValueError("IMTP interval support does not equal its registered window")
    metric_reference, operation, unit, _ = _metric_reference(
        result.metric, result.force_quantity, result.window_ms
    )
    identity = result.observation.identity
    if not isinstance(identity, IMTPMeasurementIdentity):
        raise ValueError("IMTP metric output requires IMTPMeasurementIdentity")
    expected_measurand = (
        IMTP_VERTICAL_FORCE_MEASURAND
        if result.force_quantity is IMTPForceQuantity.GROSS_VERTICAL_FORCE
        else IMTP_NET_FORCE_ABOVE_BASELINE_MEASURAND
    )
    if (
        identity.semantic.construct != IMTP_CONSTRUCT
        or identity.semantic.test_family != IMTP_TEST_FAMILY
    ):
        raise ValueError("IMTP metric output has the wrong construct or family")
    if (
        identity.semantic.measurand != expected_measurand
        or identity.semantic.metric_definition != metric_reference
    ):
        raise ValueError("IMTP metric output has the wrong measurand or metric")
    if (
        identity.semantic.protocol_identity
        != result.force_input.identity.semantic.protocol_identity
    ):
        raise ValueError("IMTP metric output does not preserve protocol identity")
    if identity.acquisition != result.force_input.identity.acquisition:
        raise ValueError("IMTP metric output does not preserve acquisition identity")
    source_processing = result.force_input.identity.processing
    expected_estimator = {
        IMTPMetric.PEAK_FORCE: IMTP_SAMPLE_MAXIMUM_METHOD,
        IMTPMetric.FORCE_AT_TIME: IMTP_EXACT_SAMPLE_AT_TIME_METHOD,
        IMTPMetric.IMPULSE: None,
        IMTPMetric.RFD: IMTP_ENDPOINT_RFD_METHOD,
    }[result.metric]
    if (
        identity.processing.event_definitions != (IMTP_ONSET_EVENT_DEFINITION,)
        or identity.processing.filtering != source_processing.filtering
        or identity.processing.filtering_status != source_processing.filtering_status
        or identity.processing.smoothing != source_processing.smoothing
        or identity.processing.resampling != source_processing.resampling
        or identity.processing.processing_state != StrengthProcessingState.DYNAMISLM_PROCESSED
        or identity.processing.estimator != expected_estimator
        or identity.processing.integration_method
        != (IMTP_TRAPEZOIDAL_INTEGRATION_METHOD if result.metric is IMTPMetric.IMPULSE else None)
    ):
        raise ValueError("IMTP metric output does not preserve processing identity")
    if result.observation.context != result.force_input.observation.context:
        raise ValueError("IMTP metric output context was rebound")
    if result.observation.result.unit != unit:
        raise ValueError("IMTP metric output unit is not registered")
    expected = _expected_metric_value(result)
    if _numeric_scalar(result.observation) != expected:
        raise ValueError("IMTP metric scalar does not reproduce from its source")
    _require_metric_lineage(
        result.observation,
        operation=operation,
        parameters=identity.processing.method_parameters,
        entity_ids=(
            result.force_input.observation.observation_id,
            result.force_input.series.signal_id,
            result.onset.occurrence_id,
            result.onset.baseline_id,
        ),
    )


def _metric_parameters(
    force: IMTPForceInput,
    onset: IMTPOnset,
    support: IMTPMetricSupport,
    metric: IMTPMetric,
    quantity: IMTPForceQuantity,
    window_ms: int | None,
    operation: RegistryReference,
    equation: str,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("metric", metric.value),
        MetadataEntry(
            "metric_definition", _metric_reference(metric, quantity, window_ms)[0].stable_id
        ),
        MetadataEntry("operation_id", operation.stable_id),
        MetadataEntry("operation_version", operation.identifier.version),
        MetadataEntry("force_quantity", quantity.value),
        MetadataEntry("equation", equation),
        MetadataEntry("window_ms", window_ms),
        MetadataEntry("trial_end_rule", support.trial_end_rule.stable_id),
        MetadataEntry("start_index", support.start_index),
        MetadataEntry("end_index", support.end_index),
        MetadataEntry("start_time_s", support.start_time_s),
        MetadataEntry("end_time_s", support.end_time_s),
        MetadataEntry("onset_occurrence_id", onset.occurrence_id.qualified),
        MetadataEntry("baseline_id", onset.baseline_id.qualified),
        MetadataEntry("onset_method", IMTP_ONSET_BASELINE_FIVE_SD_METHOD.stable_id),
        MetadataEntry("onset_parameters", canonical_json(onset.parameters)),
        MetadataEntry("source_observation_id", force.observation.observation_id.qualified),
        MetadataEntry("source_signal_id", force.series.signal_id.qualified),
        MetadataEntry("source_artifact_id", force.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", force.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", force.identity.identity_id.stable_id),
        MetadataEntry("source_timebase", canonical_json(force.series.timebase)),
        MetadataEntry("source_sample_count", len(force.series.samples)),
        MetadataEntry("filtering", canonical_json(force.identity.processing.filtering)),
        MetadataEntry("interpolation", IMTP_NO_INTERPOLATION_METHOD.stable_id),
    )


def _build_imtp_metric_observation(
    *,
    force: IMTPForceInput,
    onset: IMTPOnset,
    metric: IMTPMetric,
    quantity: IMTPForceQuantity,
    window_ms: int | None,
    support: IMTPMetricSupport,
    value: float,
    output_observation_id: InstanceIdentifier | None = None,
) -> ScientificMeasurementObservation:
    metric_reference, operation, unit, equation = _metric_reference(metric, quantity, window_ms)
    if not math.isfinite(value):
        raise ValueError("IMTP result must be finite")
    parameters = _metric_parameters(
        force, onset, support, metric, quantity, window_ms, operation, equation
    )
    digest = canonical_hash(
        {
            "metric": metric_reference,
            "operation": operation,
            "parameters": parameters,
            "value": value,
            "source_observation_id": force.observation.observation_id,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"imtp-res66:{digest}"
    )
    if observation_id.instance_type != "observation":
        raise ValueError("output_observation_id must identify an observation")
    if observation_id == force.observation.observation_id:
        raise ValueError("IMTP output observation must differ from its source")
    source_identity = force.identity
    estimator = {
        IMTPMetric.PEAK_FORCE: IMTP_SAMPLE_MAXIMUM_METHOD,
        IMTPMetric.FORCE_AT_TIME: IMTP_EXACT_SAMPLE_AT_TIME_METHOD,
        IMTPMetric.IMPULSE: None,
        IMTPMetric.RFD: IMTP_ENDPOINT_RFD_METHOD,
    }[metric]
    processing = StrengthProcessingIdentity(
        event_definitions=(IMTP_ONSET_EVENT_DEFINITION,),
        registered_operation=operation,
        method_parameters=parameters,
        estimator=estimator,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        integration_method=(
            IMTP_TRAPEZOIDAL_INTEGRATION_METHOD if metric is IMTPMetric.IMPULSE else None
        ),
        unit=unit,
        sign_convention=source_identity.acquisition.sign_convention,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = IMTPMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", f"imtp-res66-{digest}", STRENGTH_REGISTRY_VERSION
        ),
        semantic=replace(
            source_identity.semantic,
            construct=IMTP_CONSTRUCT,
            test_family=IMTP_TEST_FAMILY,
            measurand=(
                IMTP_VERTICAL_FORCE_MEASURAND
                if quantity is IMTPForceQuantity.GROSS_VERTICAL_FORCE
                else IMTP_NET_FORCE_ABOVE_BASELINE_MEASURAND
            ),
            metric_definition=metric_reference,
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"imtp-res66:{digest}"),
        content_digest=canonical_hash(
            {"value": value, "unit": unit, "metric": metric_reference, "parameters": parameters}
        ),
        media_type="application/vnd.dynamislm.imtp.scalar-metric",
        immutable=True,
    )
    base = _merge_provenance(force.observation.provenance, onset.provenance)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"imtp-res66:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (artifact.artifact_id for artifact in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=operation,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=(force.observation.observation_id, onset.baseline_id),
        source_acquisition_ids=tuple(acq.acquisition_id for acq in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
        evidence_references=(
            EvidenceReference(RES66_DECISION_STRENGTH_IMTP_VBT, "registered IMTP metric"),
        ),
    )
    lineage_edges = list(provenance.lineage_edges)
    for entity_id in (force.series.signal_id, onset.occurrence_id):
        edge = LineageEdge(
            entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in lineage_edges:
            lineage_edges.append(edge)
    provenance = replace(provenance, lineage_edges=tuple(lineage_edges))
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=force.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"imtp-res66:{digest}"),
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(ValueOrigin.DERIVED_MECHANICAL_QUANTITY, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description=(
                    "RES-66 deterministic IMTP arithmetic; measurement uncertainty is not assessed."
                ),
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


def calculate_imtp_metric(
    force: IMTPForceInput,
    onset: IMTPOnset,
    metric: IMTPMetric,
    *,
    force_quantity: IMTPForceQuantity = IMTPForceQuantity.GROSS_VERTICAL_FORCE,
    window_ms: int | None = None,
    trial_end_index: int | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPMetricResult | RefusalResult:
    """Calculate one registered IMTP quantity from an exact source series."""

    claim = "calculate registered IMTP metric"
    source_refusal = _validate_force_input(force, claim)
    if source_refusal is not None:
        return source_refusal
    if not isinstance(metric, IMTPMetric) or not isinstance(force_quantity, IMTPForceQuantity):
        return _refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION,),
            ("registered IMTPMetric and IMTPForceQuantity",),
            (force.observation.observation_id,),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    if metric is not IMTPMetric.PEAK_FORCE and (
        type(window_ms) is not int or window_ms not in _ALLOWED_WINDOWS_MS
    ):
        return _refusal(
            claim,
            (RefusalReasonCode.NO_REGISTERED_OPERATION, RefusalReasonCode.UNKNOWN_INTERPOLATION),
            ("registered IMTP interval window of 50, 100, 150, or 200 ms",),
            (force.observation.observation_id, onset.occurrence_id),
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    try:
        _validate_onset_for_force(force, onset)
        _, operation, _, equation = _metric_reference(metric, force_quantity, window_ms)
        end_index: int | None
        if metric is IMTPMetric.PEAK_FORCE:
            if window_ms is not None:
                raise ValueError("peak force must not carry a time window")
            end_index = (
                len(force.series.samples) - 1 if trial_end_index is None else trial_end_index
            )
        else:
            if trial_end_index is not None:
                raise ValueError("registered interval metrics use their window as the end")
            if window_ms is None:
                raise ValueError("registered interval metric requires window_ms")
            _required_window(window_ms)
            candidate_end_index = _exact_index_for_window(force, onset, window_ms)
            if candidate_end_index is None:
                return _refusal(
                    claim,
                    (
                        RefusalReasonCode.UNKNOWN_INTERPOLATION,
                        RefusalReasonCode.TIMEBASE_INSUFFICIENT,
                    ),
                    (
                        "an exact registered-time source sample; no nearest-sample substitution "
                        "is authorized",
                    ),
                    (force.observation.observation_id, onset.occurrence_id),
                    refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
                )
            end_index = candidate_end_index
        if end_index is None:
            raise ValueError("IMTP metric end index is unresolved")
        support = _make_support(force, onset, end_index=end_index)
        if (
            metric in {IMTPMetric.IMPULSE, IMTPMetric.RFD}
            and support.end_index == support.start_index
        ):
            raise ValueError("interval metric requires a positive duration")
        value = _expected_metric_value(
            _MetricCalculationInput(
                force_input=force,
                metric=metric,
                onset=onset,
                support=support,
                force_quantity=force_quantity,
                window_ms=window_ms,
            )
        )
        observation = _build_imtp_metric_observation(
            force=force,
            onset=onset,
            metric=metric,
            quantity=force_quantity,
            window_ms=window_ms,
            support=support,
            value=value,
            output_observation_id=output_observation_id,
        )
        return IMTPMetricResult(
            observation=observation,
            metric=metric,
            force_input=force,
            onset=onset,
            support=support,
            force_quantity=force_quantity,
            window_ms=window_ms,
        )
    except (IndexError, OverflowError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.INVALID_TIMEBASE,),
            (
                f"registered IMTP {metric.value if isinstance(metric, IMTPMetric) else metric}: "
                f"{exc}",
            ),
            (force.observation.observation_id, onset.occurrence_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


def calculate_imtp_peak_force(
    force: IMTPForceInput,
    onset: IMTPOnset,
    *,
    force_quantity: IMTPForceQuantity = IMTPForceQuantity.GROSS_VERTICAL_FORCE,
    trial_end_index: int | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPMetricResult | RefusalResult:
    return calculate_imtp_metric(
        force,
        onset,
        IMTPMetric.PEAK_FORCE,
        force_quantity=force_quantity,
        trial_end_index=trial_end_index,
        output_observation_id=output_observation_id,
    )


def calculate_imtp_force_at_time(
    force: IMTPForceInput,
    onset: IMTPOnset,
    window_ms: int,
    *,
    force_quantity: IMTPForceQuantity = IMTPForceQuantity.GROSS_VERTICAL_FORCE,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPMetricResult | RefusalResult:
    return calculate_imtp_metric(
        force,
        onset,
        IMTPMetric.FORCE_AT_TIME,
        force_quantity=force_quantity,
        window_ms=window_ms,
        output_observation_id=output_observation_id,
    )


def calculate_imtp_impulse(
    force: IMTPForceInput,
    onset: IMTPOnset,
    window_ms: int,
    *,
    force_quantity: IMTPForceQuantity = IMTPForceQuantity.GROSS_VERTICAL_FORCE,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPMetricResult | RefusalResult:
    return calculate_imtp_metric(
        force,
        onset,
        IMTPMetric.IMPULSE,
        force_quantity=force_quantity,
        window_ms=window_ms,
        output_observation_id=output_observation_id,
    )


def calculate_imtp_rfd(
    force: IMTPForceInput,
    onset: IMTPOnset,
    window_ms: int,
    *,
    force_quantity: IMTPForceQuantity = IMTPForceQuantity.GROSS_VERTICAL_FORCE,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPMetricResult | RefusalResult:
    return calculate_imtp_metric(
        force,
        onset,
        IMTPMetric.RFD,
        force_quantity=force_quantity,
        window_ms=window_ms,
        output_observation_id=output_observation_id,
    )


def refuse_imtp_peak_rfd(*, observation_ids: tuple[InstanceIdentifier, ...] = ()) -> RefusalResult:
    return _refusal(
        "calculate IMTP peak differentiated RFD",
        (RefusalReasonCode.NO_REGISTERED_OPERATION,),
        (
            "registered differentiation, smoothing, filtering, sampling, moving-window, "
            "and onset method",
        ),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPBodyMassObservation:
    """Typed, context-bound denominator authority for N/kg normalization."""

    observation: ScientificMeasurementObservation

    def __post_init__(self) -> None:
        if self.observation.identity.semantic.measurand != BODY_MASS_MEASURAND:
            raise ValueError("body-mass denominator has the wrong measurand")
        if self.observation.result.unit != KILOGRAM:
            raise ValueError("body-mass denominator must use kilograms")
        value = _numeric_scalar(self.observation)
        if value <= 0:
            raise ValueError("body-mass denominator must be positive")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.DIRECT_MEASUREMENT,
            ValueOrigin.SOURCE_REPORTED,
        }:
            raise ValueError("body-mass denominator must be direct or source-reported")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("body-mass denominator must be valid")

    @property
    def value_kg(self) -> float:
        return _numeric_scalar(self.observation)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPNormalizedForceResult:
    """N/kg result with an authoritative BODY_MASS dependency."""

    observation: ScientificMeasurementObservation
    source_force: IMTPMetricResult
    body_mass: IMTPBodyMassObservation

    def __post_init__(self) -> None:
        if self.observation.context != self.source_force.observation.context:
            raise ValueError("normalized force output context differs from force source")
        if self.observation.context != self.body_mass.observation.context:
            raise ValueError("normalized force output context differs from body mass")
        identity = self.observation.identity
        if not isinstance(identity, IMTPMeasurementIdentity):
            raise ValueError("normalized force output requires IMTP identity")
        if identity.semantic.metric_definition != IMTP_NORMALIZED_FORCE_METRIC:
            raise ValueError("normalized force output has the wrong metric")
        if identity.semantic.measurand != IMTP_NORMALIZED_FORCE_MEASURAND:
            raise ValueError("normalized force output has the wrong measurand")
        if identity.processing.registered_operation != IMTP_BODY_MASS_NORMALIZATION_METHOD:
            raise ValueError("normalized force output has the wrong operation")
        normalization = identity.processing.normalization
        if (
            normalization is None
            or normalization.method != IMTP_BODY_MASS_NORMALIZATION_METHOD
            or normalization.parameters
            != (
                MetadataEntry(
                    "body_mass_observation_id", self.body_mass.observation.observation_id.qualified
                ),
            )
        ):
            raise ValueError("normalized force output has no exact normalization identity")
        if self.observation.result.unit != NEWTON_PER_KILOGRAM:
            raise ValueError("normalized force output must use N/kg")
        expected = self.source_force.value / self.body_mass.value_kg
        if _numeric_scalar(self.observation) != expected:
            raise ValueError("normalized force value does not reproduce from numerator and mass")
        if (
            self.observation.result.classification.value_origin
            is not ValueOrigin.DERIVED_MECHANICAL_QUANTITY
        ):
            raise ValueError("normalized force must be a derived mechanical quantity")
        parameters = {entry.key: entry.value for entry in identity.processing.method_parameters}
        if (
            parameters.get("source_force_observation_id")
            != self.source_force.observation.observation_id.qualified
        ):
            raise ValueError("normalized force does not preserve force source identity")
        if (
            parameters.get("body_mass_observation_id")
            != self.body_mass.observation.observation_id.qualified
        ):
            raise ValueError("normalized force does not preserve body mass identity")
        _require_metric_lineage(
            self.observation,
            operation=IMTP_BODY_MASS_NORMALIZATION_METHOD,
            parameters=identity.processing.method_parameters,
            entity_ids=(
                self.source_force.observation.observation_id,
                self.body_mass.observation.observation_id,
            ),
        )


def normalize_imtp_force(
    force_result: IMTPMetricResult,
    body_mass: IMTPBodyMassObservation,
    *,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPNormalizedForceResult | RefusalResult:
    """Normalize a force result by a typed BODY_MASS observation only."""

    claim = "normalize IMTP force by authoritative body mass"
    try:
        _validate_imtp_metric_result(force_result)
        if not isinstance(body_mass, IMTPBodyMassObservation):
            raise ValueError("IMTP normalization requires IMTPBodyMassObservation")
        if force_result.metric not in {IMTPMetric.PEAK_FORCE, IMTPMetric.FORCE_AT_TIME}:
            raise ValueError("V1 normalization is registered only for force outputs")
        if force_result.observation.context != body_mass.observation.context:
            raise ValueError("body mass must use the exact IMTP observation context")
        value = force_result.value / body_mass.value_kg
        if not math.isfinite(value):
            raise ValueError("normalized force is not finite")
    except (TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.MASS_MEASURAND_MISMATCH,),
            (f"typed positive BODY_MASS denominator: {exc}",),
            (force_result.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    source_identity = force_result.observation.identity
    if not isinstance(source_identity, IMTPMeasurementIdentity):
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            ("IMTP numerator identity",),
            (force_result.observation.observation_id,),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    parameters = (
        MetadataEntry("operation_id", IMTP_BODY_MASS_NORMALIZATION_METHOD.stable_id),
        MetadataEntry(
            "source_force_observation_id", force_result.observation.observation_id.qualified
        ),
        MetadataEntry("source_force_metric", source_identity.semantic.metric_definition.stable_id),
        MetadataEntry("source_force_value", force_result.value),
        MetadataEntry("body_mass_observation_id", body_mass.observation.observation_id.qualified),
        MetadataEntry("body_mass_value_kg", body_mass.value_kg),
        MetadataEntry("equation", "force_N / BODY_MASS_kg"),
    )
    digest = canonical_hash(
        {
            "operation": IMTP_BODY_MASS_NORMALIZATION_METHOD,
            "parameters": parameters,
            "value": value,
        }
    ).removeprefix("sha256:")[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"imtp-normalized:{digest}"
    )
    processing = StrengthProcessingIdentity(
        event_definitions=source_identity.processing.event_definitions,
        phase_definitions=source_identity.processing.phase_definitions,
        registered_operation=IMTP_BODY_MASS_NORMALIZATION_METHOD,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=NEWTON_PER_KILOGRAM,
        sign_convention=source_identity.processing.sign_convention,
        normalization=NormalizationSpec(
            method=IMTP_BODY_MASS_NORMALIZATION_METHOD,
            parameters=(
                MetadataEntry(
                    "body_mass_observation_id", body_mass.observation.observation_id.qualified
                ),
            ),
            description="Force divided by the exact context-bound BODY_MASS observation.",
        ),
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = IMTPMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"imtp-normalized-{digest}",
            STRENGTH_REGISTRY_VERSION,
        ),
        semantic=replace(
            source_identity.semantic,
            metric_definition=IMTP_NORMALIZED_FORCE_METRIC,
            measurand=IMTP_NORMALIZED_FORCE_MEASURAND,
        ),
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=IMTP_BODY_MASS_NORMALIZATION_METHOD,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"imtp-normalized:{digest}"),
        content_digest=canonical_hash(
            {"value": value, "unit": NEWTON_PER_KILOGRAM, "parameters": parameters}
        ),
        media_type="application/vnd.dynamislm.imtp.normalized-force",
        immutable=True,
    )
    base = _merge_provenance(force_result.observation.provenance, body_mass.observation.provenance)
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"imtp-normalized:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (artifact.artifact_id for artifact in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=IMTP_BODY_MASS_NORMALIZATION_METHOD,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=(
            force_result.observation.observation_id,
            body_mass.observation.observation_id,
        ),
        source_acquisition_ids=tuple(item.acquisition_id for item in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    try:
        observation = ScientificMeasurementObservation(
            observation_id=observation_id,
            context=force_result.observation.context,
            identity=identity,
            result=MeasurementResult(
                result_id=InstanceIdentifier("result", f"imtp-normalized:{digest}"),
                value=ScalarValue(value),
                unit=NEWTON_PER_KILOGRAM,
                classification=ScientificClassification(
                    ValueOrigin.DERIVED_MECHANICAL_QUANTITY, ()
                ),
                uncertainty=UncertaintyMetadata(
                    status=UncertaintyStatus.NOT_ASSESSED,
                    description=(
                        "RES-66 deterministic normalization; denominator uncertainty is "
                        "not assessed."
                    ),
                ),
                status=ResultStatus.VALID,
            ),
            provenance=provenance,
        )
        run_edges = list(observation.provenance.lineage_edges)
        edge = LineageEdge(
            force_result.observation.observation_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        )
        if edge not in run_edges:
            run_edges.append(edge)
        observation = replace(
            observation,
            provenance=replace(observation.provenance, lineage_edges=tuple(run_edges)),
        )
        return IMTPNormalizedForceResult(observation, force_result, body_mass)
    except (TypeError, ValueError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            (f"normalized IMTP result construction: {exc}",),
            (force_result.observation.observation_id, body_mass.observation.observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPTrialMetricInput:
    """Explicit trial eligibility declaration for aggregation."""

    result: IMTPMetricResult
    eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.result, IMTPMetricResult):
            raise ValueError("trial aggregation input must contain an IMTPMetricResult")
        if not isinstance(self.eligible, bool):
            raise ValueError("trial eligibility must be boolean")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IMTPTrialAggregationResult:
    """Explicit selection/aggregation result with replayable candidates."""

    observation: ScientificMeasurementObservation
    selection_rule: RegistryReference
    candidate_results: tuple[IMTPTrialMetricInput, ...]
    selected_results: tuple[IMTPMetricResult, ...]

    def __post_init__(self) -> None:
        require_tuple(self.candidate_results, "candidate_results")
        require_tuple(self.selected_results, "selected_results")
        if self.selection_rule not in {
            IMTP_BEST_PEAK_FORCE_SELECTION,
            IMTP_MEAN_ALL_ELIGIBLE_SELECTION,
            IMTP_MEAN_BEST_N_SELECTION,
        }:
            raise ValueError("IMTP selection rule is not registered")
        if not self.selected_results:
            raise ValueError("IMTP aggregation must select at least one trial")
        _validate_imtp_aggregation_result(self)

    @property
    def value(self) -> float:
        return _numeric_scalar(self.observation)


def _aggregation_rule_reference(rule: IMTPTrialSelectionRule) -> RegistryReference:
    return {
        IMTPTrialSelectionRule.BEST_PEAK_FORCE: IMTP_BEST_PEAK_FORCE_SELECTION,
        IMTPTrialSelectionRule.MEAN_ALL_ELIGIBLE: IMTP_MEAN_ALL_ELIGIBLE_SELECTION,
        IMTPTrialSelectionRule.MEAN_BEST_N: IMTP_MEAN_BEST_N_SELECTION,
    }[rule]


def _same_imtp_trial_method(left: IMTPMetricResult, right: IMTPMetricResult) -> bool:
    return left.method_identity_key == right.method_identity_key


def _aggregation_parameters(
    rule: RegistryReference,
    candidates: tuple[IMTPTrialMetricInput, ...],
    selected: tuple[IMTPMetricResult, ...],
    best_n: int | None,
) -> tuple[MetadataEntry, ...]:
    first = selected[0]
    return (
        MetadataEntry("operation_id", IMTP_TRIAL_AGGREGATION_OPERATION.stable_id),
        MetadataEntry("selection_rule", rule.stable_id),
        MetadataEntry("best_n", best_n),
        MetadataEntry(
            "candidate_observation_ids",
            canonical_json(tuple(item.result.observation.observation_id for item in candidates)),
        ),
        MetadataEntry(
            "eligible_candidate_observation_ids",
            canonical_json(
                tuple(
                    item.result.observation.observation_id for item in candidates if item.eligible
                )
            ),
        ),
        MetadataEntry(
            "selected_observation_ids",
            canonical_json(tuple(item.observation.observation_id for item in selected)),
        ),
        MetadataEntry("metric", first.observation.identity.semantic.metric_definition.stable_id),
        MetadataEntry("aggregation_equation", "mean(selected metric scalar values)"),
    )


def _build_aggregation_observation(
    candidates: tuple[IMTPTrialMetricInput, ...],
    selected: tuple[IMTPMetricResult, ...],
    rule: RegistryReference,
    best_n: int | None,
    value: float,
    output_observation_id: InstanceIdentifier | None,
) -> ScientificMeasurementObservation:
    first = selected[0]
    source_identity = first.observation.identity
    if not isinstance(source_identity, IMTPMeasurementIdentity):
        raise ValueError("IMTP aggregation requires an IMTP source identity")
    parameters = _aggregation_parameters(rule, candidates, selected, best_n)
    digest = canonical_hash({"rule": rule, "parameters": parameters, "value": value}).removeprefix(
        "sha256:"
    )[:24]
    observation_id = output_observation_id or InstanceIdentifier(
        "observation", f"imtp-aggregation:{digest}"
    )
    processing = StrengthProcessingIdentity(
        event_definitions=source_identity.processing.event_definitions,
        phase_definitions=source_identity.processing.phase_definitions,
        registered_operation=IMTP_TRIAL_AGGREGATION_OPERATION,
        method_parameters=parameters,
        filtering=source_identity.processing.filtering,
        filtering_status=source_identity.processing.filtering_status,
        unit=first.observation.result.unit,
        sign_convention=source_identity.processing.sign_convention,
        aggregation=rule,
        smoothing=source_identity.processing.smoothing,
        resampling=source_identity.processing.resampling,
        processing_state=StrengthProcessingState.DYNAMISLM_PROCESSED,
    )
    identity = IMTPMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"imtp-aggregation-{digest}",
            STRENGTH_REGISTRY_VERSION,
        ),
        semantic=source_identity.semantic,
        acquisition=source_identity.acquisition,
        processing=processing,
        version=VersionIdentity(
            processing_method=IMTP_TRIAL_AGGREGATION_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version=RES66_SOFTWARE_VERSION,
            hardware_firmware=source_identity.version.hardware_firmware,
        ),
    )
    base = selected[0].observation.provenance
    for item in selected[1:]:
        base = _merge_provenance(base, item.observation.provenance)
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"imtp-aggregation:{digest}"),
        content_digest=canonical_hash({"value": value, "parameters": parameters}),
        media_type="application/vnd.dynamislm.imtp.aggregated-metric",
        immutable=True,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"imtp-aggregation:{digest}"),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in base.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=IMTP_TRIAL_AGGREGATION_OPERATION,
        parameters=parameters,
        software_version=RES66_SOFTWARE_VERSION,
        output_entity_id=observation_id,
    )
    provenance = _provenance_with_run(
        base,
        processing_run=run,
        output_entity_id=observation_id,
        source_observation_ids=tuple(item.observation.observation_id for item in selected),
        source_acquisition_ids=tuple(item.acquisition_id for item in base.acquisitions),
        output_artifacts=(output_artifact,),
        supported_by=(RES66_DECISION_STRENGTH_IMTP_VBT,),
    )
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=first.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"imtp-aggregation:{digest}"),
            value=ScalarValue(value),
            unit=first.observation.result.unit,
            classification=ScientificClassification(ValueOrigin.DERIVED_MECHANICAL_QUANTITY, ()),
            uncertainty=UncertaintyMetadata(status=UncertaintyStatus.NOT_ASSESSED),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


def aggregate_imtp_metric_results(
    candidates: tuple[IMTPTrialMetricInput, ...],
    selection_rule: IMTPTrialSelectionRule,
    *,
    best_n: int | None = None,
    output_observation_id: InstanceIdentifier | None = None,
) -> IMTPTrialAggregationResult | RefusalResult:
    """Select and aggregate explicitly eligible IMTP trials."""

    claim = "select and aggregate IMTP trial metrics"
    try:
        require_tuple(candidates, "candidates")
        if not candidates or any(not isinstance(item, IMTPTrialMetricInput) for item in candidates):
            raise ValueError("explicit IMTPTrialMetricInput candidates are required")
        if not isinstance(selection_rule, IMTPTrialSelectionRule):
            raise ValueError("registered IMTPTrialSelectionRule is required")
        if selection_rule is IMTPTrialSelectionRule.MEAN_BEST_N:
            if type(best_n) is not int or best_n < 1:
                raise ValueError("MEAN_BEST_N requires a positive best_n")
        elif best_n is not None:
            raise ValueError("best_n is only valid for MEAN_BEST_N")
        eligible = tuple(item.result for item in candidates if item.eligible)
        if not eligible:
            raise ValueError("at least one eligible IMTP trial is required")
        first = eligible[0]
        for result in eligible[1:]:
            if (
                result.observation.context.athlete_id != first.observation.context.athlete_id
                or result.observation.context.session_id != first.observation.context.session_id
                or result.observation.context.test_instance_id
                != first.observation.context.test_instance_id
            ):
                raise ValueError(
                    "IMTP aggregation candidates must share athlete/session/test context"
                )
            if not _same_imtp_trial_method(first, result):
                raise ValueError("IMTP aggregation candidates have different method identities")
        selected: tuple[IMTPMetricResult, ...]
        if selection_rule is IMTPTrialSelectionRule.BEST_PEAK_FORCE:
            if any(result.metric is not IMTPMetric.PEAK_FORCE for result in eligible):
                raise ValueError("best peak-force selection requires peak-force results")
            selected = (max(eligible, key=lambda item: item.value),)
        elif selection_rule is IMTPTrialSelectionRule.MEAN_ALL_ELIGIBLE:
            selected = eligible
        else:
            ranked = sorted(enumerate(eligible), key=lambda pair: (-pair[1].value, pair[0]))
            selected = tuple(result for _, result in ranked[: best_n or 0])
        value = math.fsum(item.value for item in selected) / len(selected)
        rule = _aggregation_rule_reference(selection_rule)
        observation = _build_aggregation_observation(
            candidates, selected, rule, best_n, value, output_observation_id
        )
        return IMTPTrialAggregationResult(observation, rule, candidates, selected)
    except (IndexError, OverflowError, TypeError, ValueError, ZeroDivisionError) as exc:
        return _refusal(
            claim,
            (RefusalReasonCode.TRIAL_NOT_ELIGIBLE,),
            (f"explicit IMTP trial selection/aggregation: {exc}",),
            tuple(
                item.result.observation.observation_id
                for item in candidates
                if isinstance(item, IMTPTrialMetricInput)
            ),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )


def _validate_imtp_aggregation_result(result: IMTPTrialAggregationResult) -> None:
    if not result.selected_results:
        raise ValueError("aggregation has no selected results")
    eligible = tuple(item.result for item in result.candidate_results if item.eligible)
    expected: tuple[IMTPMetricResult, ...]
    if result.selection_rule == IMTP_BEST_PEAK_FORCE_SELECTION:
        expected = (max(eligible, key=lambda item: item.value),)
    elif result.selection_rule == IMTP_MEAN_ALL_ELIGIBLE_SELECTION:
        expected = eligible
    else:
        parameter_values = {
            entry.key: entry.value
            for entry in result.observation.identity.processing.method_parameters
        }
        best_n = parameter_values.get("best_n")
        if type(best_n) is not int or best_n < 1:
            raise ValueError("aggregation best_n is not preserved")
        ranked = sorted(enumerate(eligible), key=lambda pair: (-pair[1].value, pair[0]))
        expected = tuple(item for _, item in ranked[:best_n])
    if result.selected_results != expected:
        raise ValueError("selected trials do not reproduce from the registered rule")
    if _numeric_scalar(result.observation) != math.fsum(item.value for item in expected) / len(
        expected
    ):
        raise ValueError("aggregated scalar does not reproduce from selected trials")
    first = expected[0]
    first_identity = first.observation.identity
    if not isinstance(first_identity, IMTPMeasurementIdentity):
        raise ValueError("selected trial has no IMTP identity")
    identity = result.observation.identity
    if not isinstance(identity, IMTPMeasurementIdentity):
        raise ValueError("aggregated output requires IMTP identity")
    if (
        identity.semantic.protocol_identity != first_identity.semantic.protocol_identity
        or identity.acquisition != first_identity.acquisition
    ):
        raise ValueError("aggregated output does not preserve method identity")
    if result.observation.context != first.observation.context:
        raise ValueError("aggregated output context does not match source context")
    parameters = identity.processing.method_parameters
    _require_metric_lineage(
        result.observation,
        operation=IMTP_TRIAL_AGGREGATION_OPERATION,
        parameters=parameters,
        entity_ids=tuple(item.observation.observation_id for item in expected),
    )


# Common aliases used by callers that spell the acronym in the operation name.
calculate_imtp_peak_force_metric = calculate_imtp_peak_force
calculate_imtp_force_at_registered_time = calculate_imtp_force_at_time
calculate_imtp_endpoint_rfd = calculate_imtp_rfd
aggregate_imtp_trials = aggregate_imtp_metric_results
IMTPForceSeries = IMTPForceTimeSeries
IMTPBaselineResult = IMTPBaseline
IMTPOnsetOccurrence = IMTPOnset
calculate_imtp_force_metric = calculate_imtp_metric
calculate_imtp_force_impulse = calculate_imtp_impulse
calculate_imtp_rate_of_force_development = calculate_imtp_rfd
calculate_imtp_normalized_force = normalize_imtp_force
IMTPForceMetricResult = IMTPMetricResult
calculate_imtp_peak_rfd = refuse_imtp_peak_rfd
refuse_unregistered_imtp_rfd = refuse_imtp_peak_rfd


__all__ = [
    "RES66_SOFTWARE_VERSION",
    "IMTPBaseline",
    "IMTPBaselineQC",
    "IMTPBaselineResult",
    "IMTPBaselineSegment",
    "IMTPBodyMassObservation",
    "IMTPForceInput",
    "IMTPForceMetricResult",
    "IMTPForceQuantity",
    "IMTPForceSeries",
    "IMTPForceTimeSeries",
    "IMTPMetric",
    "IMTPMetricResult",
    "IMTPMetricSupport",
    "IMTPNormalizedForceResult",
    "IMTPOnset",
    "IMTPOnsetOccurrence",
    "IMTPOnsetParameters",
    "IMTPThresholdDirection",
    "IMTPTrialAggregationResult",
    "IMTPTrialMetricInput",
    "IMTPTrialSelectionRule",
    "aggregate_imtp_metric_results",
    "aggregate_imtp_trials",
    "build_imtp_baseline",
    "calculate_imtp_endpoint_rfd",
    "calculate_imtp_force_at_registered_time",
    "calculate_imtp_force_at_time",
    "calculate_imtp_force_impulse",
    "calculate_imtp_force_metric",
    "calculate_imtp_impulse",
    "calculate_imtp_metric",
    "calculate_imtp_normalized_force",
    "calculate_imtp_peak_force",
    "calculate_imtp_peak_force_metric",
    "calculate_imtp_peak_rfd",
    "calculate_imtp_rate_of_force_development",
    "calculate_imtp_rfd",
    "create_imtp_force_input",
    "create_imtp_raw_observation",
    "detect_imtp_onset",
    "normalize_imtp_force",
    "refuse_imtp_peak_rfd",
    "refuse_unregistered_imtp_rfd",
    "source_artifact_for_imtp_series",
]
