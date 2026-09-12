"""RES-64 interpretation mapping for the qualified RES-63 Source A variables."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from dynamislm.external_load.identity import (
    AggregationContext,
    AggregationScope,
    EventHysteresisStatus,
    ExternalLoadAggregationIdentity,
    ExternalLoadDefinitionStatus,
    ExternalLoadEventDefinition,
    ExternalLoadMeasurementIdentity,
    ExternalLoadMetricFamily,
    ExternalLoadModality,
    ExternalLoadNormalizationIdentity,
    ExternalLoadProcessingIdentity,
    ExternalLoadSystemIdentity,
    ExternalLoadThresholdIdentity,
    NormalizationKind,
    ProcessingComponentStatus,
    ProcessingStepIdentity,
    ThresholdBasis,
    ThresholdBoundary,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_ACCELERATION_MEASURAND,
    EXTERNAL_LOAD_CONSTRUCT,
    EXTERNAL_LOAD_DECELERATION_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_DECELERATION_MEASURAND,
    EXTERNAL_LOAD_DISTANCE_MEASURAND,
    EXTERNAL_LOAD_DURATION_MEASURAND,
    EXTERNAL_LOAD_INPUT_PROCESSING_METHOD,
    EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
    EXTERNAL_LOAD_MAXIMUM_SPEED_METRIC,
    EXTERNAL_LOAD_METABOLIC_POWER_MEASURAND,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_METERS_PER_MINUTE,
    EXTERNAL_LOAD_MINUTE,
    EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC,
    EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
    EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
    EXTERNAL_LOAD_SECOND,
    EXTERNAL_LOAD_SOURCE_A_ACCELERATION_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_DECELERATION_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION,
    EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION,
    EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_PROVIDER_NORMALIZATION,
    EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_SPRINT_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_VECTOR7,
    EXTERNAL_LOAD_SPEED_MEASURAND,
    EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_TEST_FAMILY,
    EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
    EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC,
    EXTERNAL_LOAD_WATTS_PER_KILOGRAM,
    SOURCE_A_MAPPING_VERSION,
    SOURCE_A_VARIABLE_REGISTRY_SHA256,
)
from dynamislm.ingestion.contracts import (
    CanonicalEmpiricalRecord,
    SourceVariableIdentity,
    SourceVariableRegistry,
    SourceVariableRole,
    VariableResolutionStatus,
    stable_source_variable_id,
)
from dynamislm.measurement.identity import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MetadataEntry,
    NormalizationSpec,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentity,
    UnitReference,
    VersionIdentity,
    _require_instance,
    _require_text,
    require_tuple,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    UncertaintyMetadata,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import Provenance
from dynamislm.serialization import canonical_hash, register_serializable_type


@dataclass(frozen=True, slots=True)
class _SourceASpec:
    metric_family: ExternalLoadMetricFamily
    modality: ExternalLoadModality
    measurand: RegistryReference
    metric_reference: RegistryReference
    unit: UnitReference | None
    threshold: ExternalLoadThresholdIdentity
    normalization: ExternalLoadNormalizationIdentity
    provider_algorithm: RegistryReference | None
    event_definition: ExternalLoadEventDefinition | None
    definition_status: ExternalLoadDefinitionStatus
    value_origin: ValueOrigin


def _threshold(
    *,
    quantity: RegistryReference,
    value: float,
    unit: UnitReference,
) -> ExternalLoadThresholdIdentity:
    return ExternalLoadThresholdIdentity(
        basis=ThresholdBasis.ABSOLUTE,
        threshold_quantity=quantity,
        threshold_value=value,
        threshold_unit=unit,
        boundary=ThresholdBoundary.GREATER_THAN,
    )


def _provider_event(definition: RegistryReference) -> ExternalLoadEventDefinition:
    return ExternalLoadEventDefinition(
        definition=definition,
        minimum_duration_s=None,
        hysteresis_status=EventHysteresisStatus.UNKNOWN,
        gap_allowance_s=None,
        start_rule=None,
        end_rule=None,
    )


def _source_a_specs() -> dict[str, _SourceASpec]:
    none_threshold = ExternalLoadThresholdIdentity.none()
    no_normalization = ExternalLoadNormalizationIdentity.none()
    provider_normalization = ExternalLoadNormalizationIdentity(
        kind=NormalizationKind.OTHER_REGISTERED,
        method=EXTERNAL_LOAD_SOURCE_A_PROVIDER_NORMALIZATION,
        parameters=(MetadataEntry("provider_normalization", "source-reported"),),
    )
    provider_kwargs: dict[str, Any] = {
        "modality": ExternalLoadModality.GNSS,
        "normalization": no_normalization,
        "definition_status": ExternalLoadDefinitionStatus.PARTIAL,
        "value_origin": ValueOrigin.PROVIDER_DERIVED,
    }
    return {
        "Matchduration(min)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.MINUTES_EXPOSURE,
            modality=ExternalLoadModality.SOURCE_REPORTED,
            measurand=EXTERNAL_LOAD_DURATION_MEASURAND,
            metric_reference=EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC,
            unit=EXTERNAL_LOAD_MINUTE,
            threshold=none_threshold,
            normalization=no_normalization,
            provider_algorithm=None,
            event_definition=None,
            definition_status=ExternalLoadDefinitionStatus.RESOLVED,
            value_origin=ValueOrigin.SOURCE_REPORTED,
        ),
        "TotalDistance(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.TOTAL_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=none_threshold,
            event_definition=None,
            **provider_kwargs,
        ),
        "Relativedistance(m/min)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=none_threshold,
            normalization=provider_normalization,
            event_definition=None,
            **{key: value for key, value in provider_kwargs.items() if key != "normalization"},
        ),
        "Distance>20,0km/h(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
                value=20.0,
                unit=EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
            ),
            event_definition=None,
            **provider_kwargs,
        ),
        "Distance>25,0km/h(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
                value=25.0,
                unit=EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
            ),
            event_definition=None,
            **provider_kwargs,
        ),
        "Distance>30,0km/h(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
                value=30.0,
                unit=EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
            ),
            event_definition=None,
            **provider_kwargs,
        ),
        "Explosiveefforts(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_ACCELERATION_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_ACCELERATION_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Maxvelocity(km/h)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.MAXIMUM_SPEED,
            measurand=EXTERNAL_LOAD_SPEED_MEASURAND,
            metric_reference=EXTERNAL_LOAD_MAXIMUM_SPEED_METRIC,
            unit=EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=none_threshold,
            event_definition=None,
            **provider_kwargs,
        ),
        "Distance>20W(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_METABOLIC_POWER_MEASURAND,
                value=20.0,
                unit=EXTERNAL_LOAD_WATTS_PER_KILOGRAM,
            ),
            event_definition=None,
            **provider_kwargs,
        ),
        "Distance>55W(m)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            metric_reference=EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METER,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_METABOLIC_POWER_MEASURAND,
                value=55.0,
                unit=EXTERNAL_LOAD_WATTS_PER_KILOGRAM,
            ),
            event_definition=None,
            **provider_kwargs,
        ),
        "Playerload": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=none_threshold,
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
            event_definition=None,
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Sprints": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
            modality=ExternalLoadModality.GNSS,
            measurand=EXTERNAL_LOAD_SPEED_MEASURAND,
            metric_reference=EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC,
            unit=None,
            threshold=_threshold(
                quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
                value=25.0,
                unit=EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
            ),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_SPRINT_EVENT_DEFINITION),
            **{
                key: value
                for key, value in provider_kwargs.items()
                if key not in {"modality", "normalization"}
            },
        ),
        "Acceleration(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_ACCELERATION_MEASURAND,
            metric_reference=EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_ACCELERATION_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Deceleration(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_DECELERATION_MEASURAND,
            metric_reference=EXTERNAL_LOAD_DECELERATION_EVENT_COUNT_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_DECELERATION_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Changeofdirectiontoleft(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=None,
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Changeofdirectiontoright(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=None,
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "Jumps>40cm(IMA)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM,
            event_definition=None,
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "RHIEBoutRecoveryMean(s)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.REPEATED_HIGH_INTENSITY_EFFORT,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=EXTERNAL_LOAD_SECOND,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "RHIETotalBouts(N)": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.REPEATED_HIGH_INTENSITY_EFFORT,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
        "RHIEEffortsPerBout-Mean": _SourceASpec(
            metric_family=ExternalLoadMetricFamily.REPEATED_HIGH_INTENSITY_EFFORT,
            modality=ExternalLoadModality.INERTIAL,
            measurand=EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
            metric_reference=EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
            unit=None,
            threshold=ExternalLoadThresholdIdentity.unknown(),
            normalization=no_normalization,
            provider_algorithm=EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM,
            event_definition=_provider_event(EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION),
            definition_status=ExternalLoadDefinitionStatus.PARTIAL,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        ),
    }


_SOURCE_A_SPECS = _source_a_specs()


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadSourceMapping:
    """Exact Source A variable identity plus its RES-64 interpretation."""

    source_variable_id: str
    source_variable_identity: SourceVariableIdentity
    external_identity: ExternalLoadMeasurementIdentity
    mapping_version: str = SOURCE_A_MAPPING_VERSION
    decision_reference: RegistryReference = EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION
    source_lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.source_variable_id, "source_variable_id")
        _require_instance(
            self.source_variable_identity,
            SourceVariableIdentity,
            "source_variable_identity",
        )
        if self.source_variable_id != stable_source_variable_id(self.source_variable_identity):
            raise ValueError("source_variable_id must match the exact source variable identity")
        _require_instance(
            self.external_identity, ExternalLoadMeasurementIdentity, "external_identity"
        )
        _require_text(self.mapping_version, "mapping_version")
        if self.mapping_version != SOURCE_A_MAPPING_VERSION:
            raise ValueError("external Source A mapping must use the qualified mapping version")
        _require_instance(self.decision_reference, RegistryReference, "decision_reference")
        if self.decision_reference != EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION:
            raise ValueError("external Source A mapping must use the registered decision record")
        require_tuple(self.source_lineage, "source_lineage")
        if any(not item.strip() for item in self.source_lineage):
            raise ValueError("source_lineage must not contain empty strings")
        if self.external_identity.value_origin.value != self._expected_origin():
            raise ValueError("external identity origin does not match Source A variable role")

    def _expected_origin(self) -> str:
        if self.source_variable_identity.source_role is SourceVariableRole.DIRECT_REPORTED:
            return "SOURCE_REPORTED"
        if self.source_variable_identity.source_role is SourceVariableRole.PROVIDER_DERIVED:
            return "PROVIDER_DERIVED"
        raise ValueError("only direct-reported or provider-derived Source A variables are mappable")

    @property
    def dynamislm_recomputable(self) -> bool:
        return self.external_identity.dynamislm_recomputable

    @property
    def provider(self) -> str:
        return self.external_identity.system.provider

    @property
    def method_label(self) -> str:
        return self.source_variable_identity.source_label

    @property
    def definition_status(self) -> ExternalLoadDefinitionStatus:
        return self.external_identity.definition_status


def source_a_external_column_names() -> tuple[str, ...]:
    """Return the exact Source A columns interpreted by RES-64."""

    return tuple(_SOURCE_A_SPECS)


def _expected_source_variable(column: str) -> SourceVariableIdentity:
    from dynamislm.ingestion.adapters.unifesp_serie_a import source_a_variable_identities

    columns = (column,)
    identities = source_a_variable_identities(columns)
    if len(identities) != 1:
        raise ValueError(f"Source A variable is not registered: {column!r}")
    return identities[0]


def _external_identity_for_variable(
    variable: SourceVariableIdentity,
    spec: _SourceASpec,
    provider: str,
) -> ExternalLoadMeasurementIdentity:
    variable_id = stable_source_variable_id(variable)
    digest = canonical_hash(
        {
            "source_variable_id": variable_id,
            "mapping_version": SOURCE_A_MAPPING_VERSION,
            "decision": EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION,
        }
    ).removeprefix("sha256:")[:24]
    modality = spec.modality
    origin = spec.value_origin
    provider_derived = origin is ValueOrigin.PROVIDER_DERIVED
    system = ExternalLoadSystemIdentity(
        provider=provider,
        device_or_system=EXTERNAL_LOAD_SOURCE_A_VECTOR7 if provider_derived else None,
        provider_algorithm=spec.provider_algorithm,
        provider_algorithm_status=(
            ProcessingComponentStatus.UNKNOWN
            if provider_derived
            else ProcessingComponentStatus.NOT_APPLICABLE
        ),
    )
    source_mapping_parameters = (
        MetadataEntry("source_variable_id", variable_id),
        MetadataEntry("source_column", variable.original_column_name),
        MetadataEntry("source_label", variable.source_label),
        MetadataEntry("source_role", variable.source_role.value),
        MetadataEntry("source_threshold_or_band", variable.source_threshold_or_band),
        MetadataEntry("source_method_family", variable.source_method_family),
    )
    processing = ExternalLoadProcessingIdentity(
        method_parameters=source_mapping_parameters,
        unit=spec.unit,
        normalization=(
            NormalizationSpec(
                method=spec.normalization.method,
                parameters=spec.normalization.parameters,
            )
            if spec.normalization.method is not None
            else None
        ),
        aggregation=EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION,
        filtering_status=(
            ProcessingComponentStatus.UNKNOWN
            if provider_derived
            else ProcessingComponentStatus.NOT_APPLICABLE
        ),
        smoothing=(
            ProcessingStepIdentity.unknown()
            if provider_derived
            else ProcessingStepIdentity.not_applicable()
        ),
        resampling=(
            ProcessingStepIdentity.unknown()
            if provider_derived
            else ProcessingStepIdentity.not_applicable()
        ),
        differentiation_status=(
            ProcessingComponentStatus.UNKNOWN
            if provider_derived
            else ProcessingComponentStatus.NOT_APPLICABLE
        ),
    )
    identity = ExternalLoadMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"source-a-external-{digest}",
            "1.0.0",
        ),
        semantic=SemanticIdentity(
            construct=EXTERNAL_LOAD_CONSTRUCT,
            test_family=EXTERNAL_LOAD_TEST_FAMILY,
            protocol=None,
            measurand=spec.measurand,
            metric_definition=spec.metric_reference,
        ),
        acquisition=AcquisitionIdentity(
            device=system.device_or_system,
            raw_artifact=None,
            sampling=None,
        ),
        processing=processing,
        version=VersionIdentity(
            processing_method=EXTERNAL_LOAD_INPUT_PROCESSING_METHOD,
            method_registry_version="1.0.0",
            software_version="dynamislm-res64-source-a-mapping-1.0.0",
        ),
        modality=modality,
        value_origin=origin,
        system=system,
        threshold=spec.threshold,
        aggregation=ExternalLoadAggregationIdentity(
            session_definition=EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION,
            context=AggregationContext.MATCH,
            scope=AggregationScope.WHOLE_SESSION,
        ),
        normalization=spec.normalization,
        event_definition=spec.event_definition,
        metric_family=spec.metric_family,
        definition_status=spec.definition_status,
        dynamislm_recomputable=False,
    )
    return identity


def map_source_a_variable(
    variable: SourceVariableIdentity,
    *,
    source_variable_registry: SourceVariableRegistry | None = None,
) -> ExternalLoadSourceMapping | None:
    """Map one exact Source A variable without altering the RES-63 registry."""

    from dynamislm.ingestion.adapters.unifesp_serie_a import (
        SOURCE_A_ID,
        SOURCE_A_VERSION,
    )

    _require_instance(variable, SourceVariableIdentity, "variable")
    expected = _expected_source_variable(variable.original_column_name)
    if variable != expected:
        raise ValueError(
            "Source A variable identity does not match the qualified registry entry; "
            "threshold and provider metadata cannot be substituted"
        )
    if source_variable_registry is not None:
        _require_instance(
            source_variable_registry, SourceVariableRegistry, "source_variable_registry"
        )
        if (
            source_variable_registry.source_id != SOURCE_A_ID
            or source_variable_registry.source_version != SOURCE_A_VERSION.repository_version
            or source_variable_registry.mapping_version != SOURCE_A_MAPPING_VERSION
            or source_variable_registry.sha256 != SOURCE_A_VARIABLE_REGISTRY_SHA256
        ):
            raise ValueError(
                "Source A variable registry binding is not the qualified RES-63 registry"
            )
        source_variable_registry.entry_for(variable)
    spec = _SOURCE_A_SPECS.get(variable.original_column_name)
    if spec is None:
        return None
    if variable.resolution_status in (
        VariableResolutionStatus.UNRESOLVED,
        VariableResolutionStatus.QUARANTINED,
    ):
        return None
    return ExternalLoadSourceMapping(
        source_variable_id=stable_source_variable_id(variable),
        source_variable_identity=variable,
        external_identity=_external_identity_for_variable(
            variable,
            spec,
            variable.source_provider,
        ),
    )


def map_source_a_record(
    record: CanonicalEmpiricalRecord,
    *,
    source_variable_registry: SourceVariableRegistry | None = None,
) -> ExternalLoadSourceMapping | None:
    """Interpret one canonical Source A row/variable through RES-64."""

    from dynamislm.ingestion.adapters.unifesp_serie_a import (
        SOURCE_A_EXPECTED_SHA256,
        SOURCE_A_ID,
        SOURCE_A_VERSION,
    )

    _require_instance(record, CanonicalEmpiricalRecord, "record")
    if (
        record.source_identity.source_id != SOURCE_A_ID
        or record.version_identity.repository_version != SOURCE_A_VERSION.repository_version
        or record.mapping_version != SOURCE_A_MAPPING_VERSION
        or record.raw_row_identity.raw_artifact_sha256 != SOURCE_A_EXPECTED_SHA256
    ):
        raise ValueError("record is not bound to the qualified Source A mapping")
    if not record.population_decision.passed or not record.source_decision.passed:
        raise ValueError("Source A mapping requires passing RES-60 qualification decisions")
    mapping = map_source_a_variable(
        record.variable_identity,
        source_variable_registry=source_variable_registry,
    )
    if mapping is None:
        return None
    return replace(mapping, source_lineage=record.lineage)


def map_source_a_records(
    records: tuple[CanonicalEmpiricalRecord, ...],
    *,
    source_variable_registry: SourceVariableRegistry | None = None,
) -> tuple[ExternalLoadSourceMapping, ...]:
    """Map the external-load subset of canonical Source A records."""

    require_tuple(records, "records")
    mappings: list[ExternalLoadSourceMapping] = []
    for record in records:
        mapping = map_source_a_record(record, source_variable_registry=source_variable_registry)
        if mapping is not None:
            mappings.append(mapping)
    return tuple(mappings)


def build_external_load_observation(
    *,
    observation_id: InstanceIdentifier,
    context: ObservationContext,
    identity: ExternalLoadMeasurementIdentity,
    value: str | int | float | bool,
    provenance: Provenance,
    result_id: InstanceIdentifier | None = None,
    scientific_roles: tuple[ScientificRole, ...] = (),
) -> ScientificMeasurementObservation:
    """Build a provider/source observation using the existing generic kernel."""

    _require_instance(observation_id, InstanceIdentifier, "observation_id")
    if observation_id.instance_type != "observation":
        raise ValueError("observation_id must identify an observation")
    _require_instance(context, ObservationContext, "context")
    _require_instance(identity, ExternalLoadMeasurementIdentity, "identity")
    _require_instance(provenance, Provenance, "provenance")
    if not isinstance(scientific_roles, tuple):
        raise ValueError("scientific_roles must be an immutable tuple")
    output_result_id = result_id or InstanceIdentifier("result", observation_id.value)
    if output_result_id.instance_type != "result":
        raise ValueError("result_id must identify a result")
    unit = identity.processing.unit
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=output_result_id,
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(identity.value_origin, scientific_roles),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(),
            status=ResultStatus.VALID,
        ),
        provenance=provenance,
    )


# Descriptive aliases for the mapping and observation boundary.
source_a_mapping_for_variable = map_source_a_variable
source_a_mapping_for_record = map_source_a_record
build_provider_derived_observation = build_external_load_observation


__all__ = [
    "SOURCE_A_MAPPING_VERSION",
    "ExternalLoadSourceMapping",
    "build_external_load_observation",
    "build_provider_derived_observation",
    "map_source_a_record",
    "map_source_a_records",
    "map_source_a_variable",
    "source_a_external_column_names",
    "source_a_mapping_for_record",
    "source_a_mapping_for_variable",
]
