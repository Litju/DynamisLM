"""Deterministic BPT velocity operations and explicit power refusals."""

from __future__ import annotations

import math
from dataclasses import dataclass

from dynamislm.measurement.bench_press_throw.identity import (
    BenchPressThrowProcessingIdentity,
    BenchPressThrowSemanticIdentity,
    BPTAcquisitionIdentity,
    BPTMachineType,
    BPTMeasurementIdentity,
    BPTMovementPattern,
    BPTProcessingState,
    BPTReleaseSemantics,
)
from dynamislm.measurement.bench_press_throw.qualification import (
    BenchPressThrowVelocitySeriesEvidence,
    BPTSourceQualificationEvidence,
    require_qualified_bpt,
)
from dynamislm.measurement.bench_press_throw.registry import (
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_MEASURAND,
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION,
    BPT_REGISTRY_VERSION,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_MEASURAND,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION,
    BPT_SAMPLED_MAXIMUM_ESTIMATOR,
    BPT_SOFTWARE_VERSION,
    BPT_TEST_FAMILY,
    BPT_TIME_WEIGHTED_MEAN_ESTIMATOR,
    BPT_TIME_WEIGHTED_TRAPEZOIDAL_METHOD,
    METER_PER_SECOND,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
    WATT,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    VersionIdentity,
    _require_instance,
    _require_tuple_items,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    UncertaintyMetadata,
    UncertaintyStatus,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
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


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchPressThrowMetricResult:
    """One BPT scalar result with explicit metric and source lineage."""

    observation: ScientificMeasurementObservation
    metric: RegistryReference
    source_evidence: BenchPressThrowVelocitySeriesEvidence | None = None
    source_observations: tuple[ScientificMeasurementObservation, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.metric, RegistryReference, "metric")
        _require_tuple_items(
            self.source_observations, ScientificMeasurementObservation, "source_observations"
        )
        if not isinstance(self.observation.identity, BPTMeasurementIdentity):
            raise ValueError("BPT result requires BenchPressThrowMeasurementIdentity")
        if self.observation.identity.semantic.metric_definition != self.metric:
            raise ValueError("BPT metric does not match output identity")
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("BPT result must contain a numeric scalar")
        _finite(value.value, "BPT result")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("BPT result must be valid")
        implemented_metrics = {
            BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
            BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
        }
        if self.metric in implemented_metrics and self.source_evidence is None:
            raise ValueError("implemented BPT result must preserve source-series evidence")
        if (
            self.source_evidence is not None
            and self.source_evidence.observation not in self.source_observations
        ):
            raise ValueError("BPT result must preserve its source observation")
        runs = tuple(
            run
            for run in self.observation.provenance.processing_runs
            if run.output_entity_id == self.observation.observation_id
        )
        if len(runs) != 1:
            raise ValueError("BPT result must preserve one output processing run")
        run_id = runs[0].processing_run_id.qualified
        if self.source_evidence is not None:
            if self.metric not in {
                BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
                BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
            }:
                raise ValueError(
                    "source-series evidence is only valid for implemented derived metrics"
                )
            if not any(
                edge.from_id == self.source_evidence.observation.observation_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("BPT result is missing source evidence lineage")
            if not any(
                edge.from_id == self.source_evidence.support.support_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("BPT result is missing exact support lineage")
        for source in self.source_observations:
            if not any(
                edge.from_id == source.observation_id.qualified
                and edge.to_id == run_id
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in self.observation.provenance.lineage_edges
            ):
                raise ValueError("BPT result is missing source observation lineage")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        assert isinstance(value, ScalarValue)
        return float(value.value)

    @property
    def unit(self) -> UnitReference | None:
        return self.observation.result.unit

    @property
    def value_m_per_s(self) -> float:
        if self.unit != METER_PER_SECOND:
            raise ValueError("BPT result is not expressed in m/s")
        return self.value

    @property
    def value_w(self) -> float:
        if self.unit != WATT:
            raise ValueError("BPT result is not expressed in watts")
        return self.value


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BPTProviderMetricResult:
    """Typed view of a provider/source BPT scalar with origin preserved."""

    observation: ScientificMeasurementObservation
    metric: RegistryReference

    def __post_init__(self) -> None:
        _require_instance(self.observation, ScientificMeasurementObservation, "observation")
        _require_instance(self.metric, RegistryReference, "metric")
        if not isinstance(self.observation.identity, BPTMeasurementIdentity):
            raise ValueError("provider result requires BPT identity")
        if self.observation.identity.semantic.metric_definition != self.metric:
            raise ValueError("provider metric does not match identity")
        if self.observation.result.classification.value_origin not in {
            ValueOrigin.SOURCE_REPORTED,
            ValueOrigin.PROVIDER_DERIVED,
        }:
            raise ValueError("provider result cannot be DynamisLM-derived")
        if self.observation.result.status is not ResultStatus.VALID:
            raise ValueError("provider result must be valid")

    @property
    def value(self) -> float:
        value = self.observation.result.value
        if not isinstance(value, ScalarValue) or isinstance(value.value, bool):
            raise ValueError("provider result must contain a numeric scalar")
        return float(value.value)


def _refusal(
    claim: str,
    reasons: tuple[RefusalReasonCode | str, ...],
    missing: tuple[str, ...],
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    *,
    refusal_class: RefusalClass = RefusalClass.IDENTITY_UNRESOLVED,
    safe: tuple[str, ...] = (),
) -> RefusalResult:
    codes = tuple(item.value if isinstance(item, RefusalReasonCode) else item for item in reasons)
    digest = canonical_hash(
        {"claim": claim, "reasons": codes, "missing": missing, "observation_ids": observation_ids}
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"bench-press-throw:{digest}"),
        status=RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=claim,
        reason_codes=codes,
        missing_information=missing,
        what_can_still_be_safely_described=safe
        or ("the exact BPT source series and provider values",),
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        observation_ids=observation_ids,
    )


def _validate_protocol(evidence: BenchPressThrowVelocitySeriesEvidence) -> None:
    protocol = evidence.identity.semantic.protocol_identity
    if protocol is None:
        raise ValueError("BPT protocol identity is required")
    if protocol.machine_type is BPTMachineType.UNKNOWN:
        raise ValueError("BPT machine type is unresolved")
    if protocol.counterbalance_status.value == "UNKNOWN":
        raise ValueError("BPT counterbalance status is unresolved")
    if protocol.load_identity is None:
        raise ValueError("BPT moving-system load identity is required")
    if protocol.concentric_pattern is BPTMovementPattern.UNKNOWN:
        raise ValueError("BPT movement pattern is unresolved")
    if evidence.acquisition.device is None:
        raise ValueError("BPT measuring device identity is required")
    if evidence.acquisition.sensor_modality.value == "UNKNOWN":
        raise ValueError("BPT sensor modality is unresolved")
    if not evidence.series.velocity_frame or (
        evidence.series.sign_convention.reference is None
        and evidence.series.sign_convention.positive_direction is None
    ):
        raise ValueError("BPT velocity frame and sign convention are required")
    if (
        evidence.support.includes_post_release_samples
        and protocol.release_semantics is BPTReleaseSemantics.UNKNOWN
    ):
        raise ValueError("post-release support requires explicit BPT release semantics")


def _validate_evidence(
    evidence: BenchPressThrowVelocitySeriesEvidence,
    expected_metric: RegistryReference,
    qualification: BPTSourceQualificationEvidence | None,
) -> None:
    if not isinstance(evidence, BenchPressThrowVelocitySeriesEvidence):
        raise ValueError("qualified BPT velocity-series evidence is required")
    _validate_protocol(evidence)
    if evidence.support.metric != expected_metric:
        raise ValueError("support metric does not match requested BPT operation")
    if qualification is not None:
        require_qualified_bpt(qualification, evidence.observation)


def _output_identity(
    evidence: BenchPressThrowVelocitySeriesEvidence,
    *,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
) -> BPTMeasurementIdentity:
    source = evidence.identity
    acquisition = source.acquisition
    return BPTMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"bpt-{operation.identifier.key}-{canonical_hash(parameters).removeprefix('sha256:')[:24]}",
            BPT_REGISTRY_VERSION,
        ),
        semantic=BenchPressThrowSemanticIdentity(
            construct=source.semantic.construct,
            test_family=BPT_TEST_FAMILY,
            protocol=source.semantic.protocol,
            measurand=measurand,
            metric_definition=metric,
            protocol_identity=source.semantic.protocol_identity,
        ),
        acquisition=BPTAcquisitionIdentity(
            device=acquisition.device,
            raw_artifact=acquisition.raw_artifact,
            sensor_channel=acquisition.sensor_channel,
            sampling=acquisition.sampling,
            calibration_reference=acquisition.calibration_reference,
            hardware_firmware=acquisition.hardware_firmware,
            acquisition_instance_id=acquisition.acquisition_instance_id,
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=acquisition.timebase,
            axis_or_frame=acquisition.axis_or_frame,
            source_series_digest=acquisition.source_series_digest,
        ),
        processing=BenchPressThrowProcessingIdentity(
            registered_operation=operation,
            estimator=(
                BPT_SAMPLED_MAXIMUM_ESTIMATOR
                if operation == BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION
                else BPT_TIME_WEIGHTED_MEAN_ESTIMATOR
            ),
            method_parameters=parameters,
            filtering=source.processing.filtering,
            differentiation_method=source.processing.differentiation_method,
            integration_method=(
                None
                if operation == BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION
                else BPT_TIME_WEIGHTED_TRAPEZOIDAL_METHOD
            ),
            unit=METER_PER_SECOND,
            sign_convention=source.processing.sign_convention,
            normalization=source.processing.normalization,
            trial_selection=source.processing.trial_selection,
            aggregation=source.processing.aggregation,
            timebase=evidence.series.timebase,
            processing_state=BPTProcessingState.DYNAMISLM_PROCESSED,
        ),
        version=VersionIdentity(
            processing_method=operation,
            method_registry_version=BPT_REGISTRY_VERSION,
            software_version=BPT_SOFTWARE_VERSION,
            hardware_firmware=acquisition.hardware_firmware,
        ),
    )


def _build_derived(
    evidence: BenchPressThrowVelocitySeriesEvidence,
    *,
    value: float,
    metric: RegistryReference,
    measurand: RegistryReference,
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
) -> BenchPressThrowMetricResult:
    numeric = _finite(value, "BPT derived value")
    identity = _output_identity(
        evidence,
        metric=metric,
        measurand=measurand,
        operation=operation,
        parameters=parameters,
    )
    digest = canonical_hash(
        {
            "operation": operation,
            "metric": metric,
            "value": numeric,
            "parameters": parameters,
            "source_observation_id": evidence.observation.observation_id,
            "source_series_digest": evidence.source_series_digest,
            "support": evidence.support,
        }
    ).removeprefix("sha256:")[:24]
    output_id = InstanceIdentifier("observation", f"bpt:{operation.identifier.key}:{digest}")
    output_artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"bpt-result:{digest}"),
        content_digest=canonical_hash({"identity": identity, "value": numeric, "metric": metric}),
        media_type="application/vnd.dynamislm.bench-press-throw.scalar-metric",
        immutable=True,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"bpt:{operation.identifier.key}:{digest}"
        ),
        source_artifact_ids=tuple(
            sorted(
                (item.artifact_id for item in evidence.observation.provenance.source_artifacts),
                key=lambda item: item.qualified,
            )
        ),
        method=operation,
        parameters=parameters,
        software_version=BPT_SOFTWARE_VERSION,
        output_entity_id=output_id,
    )
    if not run.source_artifact_ids:
        raise ValueError("BPT derived result requires source artifacts")
    edges = list(evidence.observation.provenance.lineage_edges)
    for entity_id in (
        evidence.observation.observation_id,
        evidence.series.series_id,
        evidence.support.support_id,
        *run.source_artifact_ids,
    ):
        edge = LineageEdge(
            entity_id.qualified, run.processing_run_id.qualified, LineageRelation.DERIVED_FROM
        )
        if edge not in edges:
            edges.append(edge)
    for acquisition in evidence.observation.provenance.acquisitions:
        edge = LineageEdge(
            acquisition.acquisition_id.qualified,
            run.processing_run_id.qualified,
            LineageRelation.PROCESSED_AS,
        )
        if edge not in edges:
            edges.append(edge)
    decision_edge = LineageEdge(
        RES68_DECISION_EXPLOSIVE_TEST_FAMILY.stable_id,
        run.processing_run_id.qualified,
        LineageRelation.SUPPORTED_BY,
    )
    if decision_edge not in edges:
        edges.append(decision_edge)
    for edge in (
        LineageEdge(
            run.processing_run_id.qualified,
            output_artifact.artifact_id.qualified,
            LineageRelation.PRODUCED,
        ),
        LineageEdge(run.processing_run_id.qualified, output_id.qualified, LineageRelation.PRODUCED),
    ):
        if edge not in edges:
            edges.append(edge)
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", output_id.value),
        source_artifacts=tuple(
            sorted(
                (*evidence.observation.provenance.source_artifacts, output_artifact),
                key=lambda item: item.artifact_id.qualified,
            )
        ),
        acquisitions=evidence.observation.provenance.acquisitions,
        processing_runs=(*evidence.observation.provenance.processing_runs, run),
        lineage_edges=tuple(
            sorted(edges, key=lambda item: (item.from_id, item.to_id, item.relation.value))
        ),
        evidence_references=tuple(
            dict.fromkeys(
                (
                    *evidence.observation.provenance.evidence_references,
                    EvidenceReference(RES68_DECISION_EXPLOSIVE_TEST_FAMILY),
                )
            )
        ),
        metrological_traceability=evidence.observation.provenance.metrological_traceability,
        recorded_at=evidence.observation.provenance.recorded_at
        or evidence.observation.context.observed_at,
    )
    observation = ScientificMeasurementObservation(
        observation_id=output_id,
        context=evidence.observation.context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"bpt:{operation.identifier.key}:{digest}"),
            value=ScalarValue(numeric),
            unit=METER_PER_SECOND,
            classification=ScientificClassification(
                ValueOrigin.DYNAMISLM_DERIVED,
                (ScientificRole.PERFORMANCE_OUTCOME,),
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(
                status=UncertaintyStatus.NOT_ASSESSED,
                description="RES-68 deterministic BPT arithmetic; uncertainty is not assessed.",
            ),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )
    return BenchPressThrowMetricResult(
        observation=observation,
        metric=metric,
        source_evidence=evidence,
        source_observations=(evidence.observation,),
    )


def calculate_bpt_sampled_maximum_bar_velocity(
    evidence: BenchPressThrowVelocitySeriesEvidence,
    qualification: BPTSourceQualificationEvidence | None = None,
    *,
    start_index: int | None = None,
    end_index: int | None = None,
) -> BenchPressThrowMetricResult | RefusalResult:
    """Calculate sampled Vmax over exact registered support, without interpolation."""

    claim = "calculate BPT sampled maximum bar velocity"
    try:
        if start_index is not None or end_index is not None:
            return _refusal(
                claim,
                (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
                ("qualified BenchPressThrowMetricSupport; raw caller indices are forbidden",),
                (evidence.observation.observation_id,)
                if isinstance(evidence, BenchPressThrowVelocitySeriesEvidence)
                else (),
            )
        _validate_evidence(evidence, BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC, qualification)
        samples = evidence.series.samples[
            evidence.support.start_index : evidence.support.end_index + 1
        ]
        if not samples:
            raise ValueError("BPT support contains no samples")
        value = max(sample[1] for sample in samples)
        parameters = (
            MetadataEntry("support_id", evidence.support.support_id.qualified),
            MetadataEntry("source_series_digest", evidence.source_series_digest),
            MetadataEntry("start_index", evidence.support.start_index),
            MetadataEntry("end_index", evidence.support.end_index),
            MetadataEntry("support_definition", evidence.support.support_definition),
            MetadataEntry(
                "includes_post_release_samples", evidence.support.includes_post_release_samples
            ),
            MetadataEntry("estimator", "sampled maximum over exact support; no interpolation"),
        )
        return _build_derived(
            evidence,
            value=value,
            metric=BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
            measurand=BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_MEASURAND,
            operation=BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION,
            parameters=parameters,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            ("qualified exact BPT Vmax support, series digest and protocol identity",),
            (evidence.observation.observation_id,)
            if isinstance(evidence, BenchPressThrowVelocitySeriesEvidence)
            else (),
        )


def calculate_bpt_dynamislm_time_weighted_mean_bar_velocity(
    evidence: BenchPressThrowVelocitySeriesEvidence,
    qualification: BPTSourceQualificationEvidence | None = None,
    *,
    start_index: int | None = None,
    end_index: int | None = None,
) -> BenchPressThrowMetricResult | RefusalResult:
    """Integrate exact BPT samples over actual timestamps and divide by duration."""

    claim = "calculate DynamisLM time-weighted mean BPT bar velocity"
    try:
        if start_index is not None or end_index is not None:
            return _refusal(
                claim,
                (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
                ("qualified BenchPressThrowMetricSupport; raw caller indices are forbidden",),
                (evidence.observation.observation_id,)
                if isinstance(evidence, BenchPressThrowVelocitySeriesEvidence)
                else (),
            )
        _validate_evidence(
            evidence,
            BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
            qualification,
        )
        start = evidence.support.start_index
        end = evidence.support.end_index
        if end <= start:
            raise ValueError("time-weighted BPT mean requires at least two support samples")
        duration = evidence.support.end_time_s - evidence.support.start_time_s
        if duration <= 0 or not math.isfinite(duration):
            raise ValueError("BPT support duration must be finite and positive")
        samples = evidence.series.samples[start : end + 1]
        area = math.fsum(
            0.5
            * (samples[offset - 1][1] + samples[offset][1])
            * (samples[offset][0] - samples[offset - 1][0])
            for offset in range(1, len(samples))
        )
        value = area / duration
        parameters = (
            MetadataEntry("support_id", evidence.support.support_id.qualified),
            MetadataEntry("source_series_digest", evidence.source_series_digest),
            MetadataEntry("start_index", start),
            MetadataEntry("end_index", end),
            MetadataEntry("support_definition", evidence.support.support_definition),
            MetadataEntry(
                "includes_post_release_samples", evidence.support.includes_post_release_samples
            ),
            MetadataEntry("integration_method", "sample-attached trapezoidal integration"),
            MetadataEntry("time_weighted_mean_equation", "integral(v dt) / (t[b] - t[a])"),
        )
        return _build_derived(
            evidence,
            value=value,
            metric=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
            measurand=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_MEASURAND,
            operation=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION,
            parameters=parameters,
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return _refusal(
            claim,
            (RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH,),
            ("qualified exact BPT time support, actual timestamps and positive duration",),
            (evidence.observation.observation_id,)
            if isinstance(evidence, BenchPressThrowVelocitySeriesEvidence)
            else (),
        )


def _unregistered(
    claim: str,
    evidence: object | None = None,
    reason: RefusalReasonCode | str = RefusalReasonCode.NO_REGISTERED_OPERATION,
) -> RefusalResult:
    observation_ids = (
        (evidence.observation.observation_id,)
        if isinstance(evidence, BenchPressThrowVelocitySeriesEvidence)
        else ()
    )
    return _refusal(
        claim,
        (reason, "COMPUTATION_NOT_REGISTERED"),
        ("a separately registered BPT operation with complete method inputs",),
        observation_ids,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        safe=("the exact BPT velocity series and any provider-reported value",),
    )


def calculate_bpt_mean_propulsive_velocity(
    evidence: BenchPressThrowVelocitySeriesEvidence | None = None,
) -> RefusalResult:
    """MPV is representable from provider evidence but not computed in V1."""

    return _unregistered("calculate BPT mean propulsive velocity", evidence)


def calculate_bpt_mean_power(
    evidence: BenchPressThrowVelocitySeriesEvidence | None = None,
) -> RefusalResult:
    return _unregistered("calculate BPT mean power", evidence)


def calculate_bpt_peak_power(
    evidence: BenchPressThrowVelocitySeriesEvidence | None = None,
) -> RefusalResult:
    return _unregistered("calculate BPT peak power", evidence)


def calculate_bpt_load_times_velocity_power(
    load_value: float | None = None,
    velocity_value: float | None = None,
) -> RefusalResult:
    """Reject the non-registered generic load-times-velocity shortcut."""

    return _unregistered("calculate generic BPT load times velocity power")


def wrap_bpt_provider_metric(
    observation: ScientificMeasurementObservation,
    metric: RegistryReference,
) -> BPTProviderMetricResult | RefusalResult:
    try:
        return BPTProviderMetricResult(observation=observation, metric=metric)
    except (AttributeError, TypeError, ValueError):
        return _refusal(
            "represent provider BPT metric",
            (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            ("provider metric identity and source/provider origin",),
            (observation.observation_id,)
            if isinstance(observation, ScientificMeasurementObservation)
            else (),
        )


# Expanded aliases are intentionally operation aliases, not metric aliases.
calculate_bpt_vmax = calculate_bpt_sampled_maximum_bar_velocity
calculate_bpt_time_weighted_mean_velocity = calculate_bpt_dynamislm_time_weighted_mean_bar_velocity
calculate_bpt_dynamislm_mean_velocity = calculate_bpt_dynamislm_time_weighted_mean_bar_velocity


__all__ = [
    "BPTProviderMetricResult",
    "BenchPressThrowMetricResult",
    "calculate_bpt_dynamislm_mean_velocity",
    "calculate_bpt_dynamislm_time_weighted_mean_bar_velocity",
    "calculate_bpt_load_times_velocity_power",
    "calculate_bpt_mean_power",
    "calculate_bpt_mean_propulsive_velocity",
    "calculate_bpt_peak_power",
    "calculate_bpt_sampled_maximum_bar_velocity",
    "calculate_bpt_time_weighted_mean_velocity",
    "calculate_bpt_vmax",
    "wrap_bpt_provider_metric",
]
