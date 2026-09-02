"""Deterministic CMJ event definitions, detectors, and occurrences.

This module stops at sample-attached movement onset, contact loss, and contact
regain.  It intentionally does not estimate force minus weight, integrate a
signal, infer kinematics, calculate jump height, or create CMJ phase objects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.cmj.comparability import (
    CMJComparabilityRequest,
    assess_cmj_acquisition_comparability,
)
from dynamislm.measurement.cmj.identity import CMJMeasurementIdentity
from dynamislm.measurement.cmj.registry import (
    CMJ_EVENT_COMPARABILITY_RULE,
    CMJ_LANDING_ABSOLUTE_FORCE_METHOD_REF,
    CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION_REF,
    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD_REF,
    CMJ_MOVEMENT_ONSET_EVENT_DEFINITION_REF,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD_REF,
    CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION_REF,
    RES36_DECISION_EVENT_SEMANTICS,
    RES36_DECISION_LANDING,
    RES36_DECISION_MOVEMENT_ONSET,
    RES36_DECISION_TAKEOFF,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
from dynamislm.measurement.cmj.weighing import (
    CMJForceInput,
    SystemWeightResult,
    TotalSupportedForceResult,
    WeighingSegment,
    _as_force_input,
    _force_semantics_refusal,
    _input_common_refusal,
    _merge_provenance,
    _provenance_with_run,
    _weight_input_refusal,
    construct_total_supported_vertical_force,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    require_tuple,
)
from dynamislm.provenance.models import EvidenceReference, ProcessingRun, Provenance
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import canonical_hash, canonical_json, register_serializable_type

RES36_SOFTWARE_VERSION = "dynamislm-res36-1.0.0"


class CMJEventLabel(StrEnum):
    """The three event boundaries owned by RES-36."""

    MOVEMENT_ONSET = "MOVEMENT_ONSET"
    TAKEOFF_CONTACT_LOSS = "TAKEOFF_CONTACT_LOSS"
    LANDING_CONTACT_REGAIN = "LANDING_CONTACT_REGAIN"
    TAKEOFF = "TAKEOFF_CONTACT_LOSS"
    LANDING = "LANDING_CONTACT_REGAIN"


class CMJEventThresholdFamily(StrEnum):
    """Registered threshold families, not threshold values."""

    BASELINE_SD_DEVIATION = "BASELINE_SD_DEVIATION"
    ABSOLUTE_FORCE = "ABSOLUTE_FORCE"


class CMJThresholdDirection(StrEnum):
    """Strict sample comparison direction for a registered detector."""

    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    ABOVE_THRESHOLD = "ABOVE_THRESHOLD"


class CMJEventOccurrenceStatus(StrEnum):
    DETECTED = "DETECTED"


class CMJEventQCCode(StrEnum):
    """Structural detector QC, never a biological quality score."""

    MULTIPLE_CANDIDATE_CROSSINGS = "MULTIPLE_CANDIDATE_CROSSINGS"
    EVENT_NEAR_SIGNAL_BOUNDARY = "EVENT_NEAR_SIGNAL_BOUNDARY"


def _require_finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _require_nonnegative_index(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJEventDefinition:
    """A semantic event boundary, independent of one observed occurrence."""

    reference: RegistryReference
    label: CMJEventLabel

    def __post_init__(self) -> None:
        if self.reference.identifier.object_type != "event-definition":
            raise ValueError("event definition reference must have object_type event-definition")
        if not isinstance(self.label, CMJEventLabel):
            raise ValueError("event definition label must be a CMJEventLabel")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJEventDetectorMethod:
    """A versioned detector identity with no embedded threshold parameters."""

    reference: RegistryReference
    event_definition: CMJEventDefinition
    threshold_family: CMJEventThresholdFamily
    decision_reference: RegistryReference

    def __post_init__(self) -> None:
        if self.reference.identifier.object_type != "event-method":
            raise ValueError("event detector method reference must have object_type event-method")
        if not isinstance(self.threshold_family, CMJEventThresholdFamily):
            raise ValueError("threshold_family must be a registered CMJEventThresholdFamily")
        if self.decision_reference.identifier.object_type != "decision-record":
            raise ValueError("event detector method must cite a decision-record reference")

    @property
    def version(self) -> str:
        return self.reference.identifier.version


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJEventDetectorParameters:
    """Explicit detector parameters; no threshold or dwell default is hidden."""

    threshold_n: float | None = None
    baseline_observation_id: InstanceIdentifier | None = None
    baseline_segment: WeighingSegment | None = None
    baseline_mean_force_n: float | None = None
    baseline_standard_deviation_n: float | None = None
    sigma_multiplier: float | None = None
    direction: CMJThresholdDirection | None = None
    dwell_samples: int | None = None
    search_start_index: int | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("threshold_n", self.threshold_n),
            ("baseline_mean_force_n", self.baseline_mean_force_n),
            ("baseline_standard_deviation_n", self.baseline_standard_deviation_n),
            ("sigma_multiplier", self.sigma_multiplier),
        ):
            if value is not None:
                _require_finite(value, field_name)
        if (
            self.baseline_standard_deviation_n is not None
            and self.baseline_standard_deviation_n < 0
        ):
            raise ValueError("baseline_standard_deviation_n must not be negative")
        if self.sigma_multiplier is not None and self.sigma_multiplier < 0:
            raise ValueError("sigma_multiplier must not be negative")
        if self.direction is not None and not isinstance(self.direction, CMJThresholdDirection):
            raise ValueError("direction must be a CMJThresholdDirection")
        if self.dwell_samples is not None:
            if isinstance(self.dwell_samples, bool) or not isinstance(self.dwell_samples, int):
                raise ValueError("dwell_samples must be an integer")
            if self.dwell_samples < 1:
                raise ValueError("dwell_samples must be at least one")
        if self.search_start_index is not None:
            _require_nonnegative_index(self.search_start_index, "search_start_index")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJEventOccurrence:
    """One concrete sample-attached event with complete detector lineage."""

    occurrence_id: InstanceIdentifier
    definition: CMJEventDefinition
    source_observation_id: InstanceIdentifier
    source_signal_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    source_acquisition_id: InstanceIdentifier
    source_measurement_identity: CMJMeasurementIdentity
    source_timebase: SignalTimebase
    detector_method: CMJEventDetectorMethod
    detector_parameters: CMJEventDetectorParameters
    sample_index: int
    event_time_s: float
    effective_threshold_n: float
    status: CMJEventOccurrenceStatus
    qc_codes: tuple[CMJEventQCCode, ...]
    decision_reference: RegistryReference
    provenance: Provenance
    preceding_event_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        if self.detector_method.event_definition != self.definition:
            raise ValueError("event occurrence definition must match detector method definition")
        if self.decision_reference != self.detector_method.decision_reference:
            raise ValueError("event occurrence decision reference must match detector method")
        _require_nonnegative_index(self.sample_index, "sample_index")
        _require_finite(self.event_time_s, "event_time_s")
        _require_finite(self.effective_threshold_n, "effective_threshold_n")
        if not isinstance(self.status, CMJEventOccurrenceStatus):
            raise ValueError("status must be a CMJEventOccurrenceStatus")
        require_tuple(self.qc_codes, "qc_codes")
        if any(not isinstance(code, CMJEventQCCode) for code in self.qc_codes):
            raise ValueError("qc_codes must contain CMJEventQCCode values")
        matching_runs = tuple(
            run
            for run in self.provenance.processing_runs
            if run.output_observation_id == self.occurrence_id
        )
        if len(matching_runs) != 1:
            raise ValueError("event occurrence must have exactly one output processing run")
        if matching_runs[0].method != self.detector_method.reference:
            raise ValueError("event occurrence processing run method must match detector method")

    @property
    def event_definition(self) -> CMJEventDefinition:
        return self.definition

    @property
    def event_method(self) -> CMJEventDetectorMethod:
        return self.detector_method


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJEventComparabilityRequest:
    """Claim-relative pair request for two concrete CMJ event occurrences."""

    request_id: InstanceIdentifier
    left_event_id: InstanceIdentifier
    right_event_id: InstanceIdentifier
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()
    material_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("claim must not be empty")
        if self.left_event_id == self.right_event_id:
            raise ValueError("event comparability requires two distinct occurrences")
        require_tuple(self.requested_transformations, "requested_transformations")
        require_tuple(self.material_dimensions, "material_dimensions")
        if any(not item.strip() for item in self.material_dimensions):
            raise ValueError("material dimensions must not contain empty strings")


CMJ_MOVEMENT_ONSET_EVENT_DEFINITION = CMJEventDefinition(
    reference=CMJ_MOVEMENT_ONSET_EVENT_DEFINITION_REF,
    label=CMJEventLabel.MOVEMENT_ONSET,
)
CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION = CMJEventDefinition(
    reference=CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION_REF,
    label=CMJEventLabel.TAKEOFF_CONTACT_LOSS,
)
CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION = CMJEventDefinition(
    reference=CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION_REF,
    label=CMJEventLabel.LANDING_CONTACT_REGAIN,
)

CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD = CMJEventDetectorMethod(
    reference=CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD_REF,
    event_definition=CMJ_MOVEMENT_ONSET_EVENT_DEFINITION,
    threshold_family=CMJEventThresholdFamily.BASELINE_SD_DEVIATION,
    decision_reference=RES36_DECISION_MOVEMENT_ONSET,
)
CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD = CMJEventDetectorMethod(
    reference=CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD_REF,
    event_definition=CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION,
    threshold_family=CMJEventThresholdFamily.ABSOLUTE_FORCE,
    decision_reference=RES36_DECISION_TAKEOFF,
)
CMJ_LANDING_ABSOLUTE_FORCE_METHOD = CMJEventDetectorMethod(
    reference=CMJ_LANDING_ABSOLUTE_FORCE_METHOD_REF,
    event_definition=CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION,
    threshold_family=CMJEventThresholdFamily.ABSOLUTE_FORCE,
    decision_reference=RES36_DECISION_LANDING,
)

CMJ_REGISTERED_EVENT_METHODS = (
    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
    CMJ_LANDING_ABSOLUTE_FORCE_METHOD,
)


def _event_refusal(
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...],
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
    refusal_class: RefusalClass = RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    code_values = tuple(code.value for code in reason_codes)
    key = canonical_hash(
        {
            "blocked_claim": blocked_claim,
            "reason_codes": code_values,
            "missing_information": missing_information,
            "observation_ids": tuple(item.qualified for item in observation_ids),
        }
    ).removeprefix("sha256:")[:24]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"res36-event:{key}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=code_values,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "the qualified source force observation remains independently describable",
            "no unregistered CMJ phase or derived performance quantity is emitted",
        ),
        observation_ids=observation_ids,
    )


def _force_observation_ids(force: CMJForceInput) -> tuple[InstanceIdentifier, ...]:
    return (force.observation.observation_id,)


def _force_input_for_events(
    value: CMJForceInput | TotalSupportedForceResult,
    claim: str,
) -> CMJForceInput | RefusalResult:
    if isinstance(value, TotalSupportedForceResult):
        total = value
    elif isinstance(value, CMJForceInput):
        total_result = construct_total_supported_vertical_force(value)
        if isinstance(total_result, RefusalResult):
            return total_result
        total = total_result
    else:
        return _event_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            ("CMJForceInput or TotalSupportedForceResult",),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    force_input = _as_force_input(total)
    source_refusal = _input_common_refusal(force_input, claim)
    if source_refusal is not None:
        return source_refusal
    semantics_refusal = _force_semantics_refusal(force_input, claim)
    if semantics_refusal is not None:
        return semantics_refusal
    if force_input.signal.timebase is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.TIMEBASE_INSUFFICIENT,),
            ("qualified regular or explicit signal timebase",),
            observation_ids=_force_observation_ids(force_input),
        )
    return force_input


def _method_refusal(
    method: CMJEventDetectorMethod,
    expected: CMJEventDetectorMethod,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult | None:
    if not isinstance(method, CMJEventDetectorMethod) or method != expected:
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_METHOD_NOT_REGISTERED,),
            (expected.reference.stable_id,),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        )
    return None


def _common_parameter_refusal(
    parameters: CMJEventDetectorParameters,
    *,
    expected_direction: CMJThresholdDirection,
    search_start_required: bool,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult | None:
    if not isinstance(parameters, CMJEventDetectorParameters):
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("CMJEventDetectorParameters",),
            observation_ids=observation_ids,
        )
    if parameters.direction is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit threshold crossing direction",),
            observation_ids=observation_ids,
        )
    if parameters.direction is not expected_direction:
        return _event_refusal(
            claim,
            (RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE,),
            (f"registered direction {expected_direction.value}",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if parameters.dwell_samples is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit dwell_samples",),
            observation_ids=observation_ids,
        )
    if search_start_required and parameters.search_start_index is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit search_start_index",),
            observation_ids=observation_ids,
        )
    if not search_start_required and parameters.search_start_index is not None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_PARAMETER_MISMATCH,),
            ("landing search origin derived from takeoff.sample_index + 1",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    return None


def _has_baseline_parameters(parameters: CMJEventDetectorParameters) -> bool:
    return any(
        value is not None
        for value in (
            parameters.baseline_observation_id,
            parameters.baseline_segment,
            parameters.baseline_mean_force_n,
            parameters.baseline_standard_deviation_n,
            parameters.sigma_multiplier,
        )
    )


def _baseline_refusal(
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
    missing: str,
    *,
    reason: RefusalReasonCode = RefusalReasonCode.BASELINE_QC_REQUIRED,
    refusal_class: RefusalClass = RefusalClass.IDENTITY_UNRESOLVED,
) -> RefusalResult:
    return _event_refusal(
        claim,
        (reason,),
        (missing,),
        observation_ids=observation_ids,
        refusal_class=refusal_class,
    )


def _validate_onset_baseline(
    force: CMJForceInput,
    baseline: SystemWeightResult | None,
    parameters: CMJEventDetectorParameters,
    claim: str,
) -> RefusalResult | None:
    observation_ids = _force_observation_ids(force)
    if baseline is None:
        return _baseline_refusal(
            claim,
            observation_ids,
            "exact RES-35 SystemWeightResult for the source force observation",
            reason=RefusalReasonCode.BASELINE_REQUIRED,
        )
    if not isinstance(baseline, SystemWeightResult):
        return _baseline_refusal(
            claim, observation_ids, "RES-35 SystemWeightResult and baseline QC"
        )
    baseline_refusal = _weight_input_refusal(baseline.observation, claim)
    if baseline_refusal is not None:
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "valid RES-35 system-weight processing lineage and baseline QC",
        )
    segment = baseline.segment
    if (
        segment.source_signal_id != force.signal.signal_id
        or segment.source_artifact_id != force.source_artifact.artifact_id
        or segment.source_measurement_identity_id != force.identity.identity_id
        or segment.end_index > len(force.signal.samples)
    ):
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "baseline segment linked to the exact source force signal, artifact, and identity",
        )
    if baseline.observation.context != force.observation.context:
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "baseline observation from the exact force observation context",
        )
    if parameters.baseline_observation_id != baseline.observation.observation_id:
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "baseline_observation_id equal to the supplied SystemWeightResult",
        )
    if parameters.baseline_segment != segment:
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "baseline_segment equal to the supplied RES-35 weighing segment",
        )
    if (
        parameters.baseline_mean_force_n != baseline.qc.mean_force_n
        or parameters.baseline_standard_deviation_n != baseline.qc.standard_deviation_n
    ):
        return _baseline_refusal(
            claim,
            (*observation_ids, baseline.observation.observation_id),
            "baseline mean and standard deviation copied exactly from RES-35 QC",
        )
    if parameters.sigma_multiplier is None:
        return _baseline_refusal(
            claim,
            observation_ids,
            "explicit sigma_multiplier",
            reason=RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if parameters.threshold_n is not None:
        return _baseline_refusal(
            claim,
            observation_ids,
            "baseline-SD parameters without an absolute threshold_n",
            reason=RefusalReasonCode.EVENT_PARAMETER_MISMATCH,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if parameters.search_start_index is None:
        return _baseline_refusal(
            claim,
            observation_ids,
            "explicit search_start_index",
            reason=RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    if parameters.search_start_index < segment.end_index:
        return _baseline_refusal(
            claim,
            observation_ids,
            "movement-onset search after the half-open weighing segment",
            reason=RefusalReasonCode.EVENT_ORDER_INVALID,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if parameters.search_start_index >= len(force.signal.samples):
        return _baseline_refusal(
            claim,
            observation_ids,
            "search_start_index inside source sample support",
            reason=RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
        )
    return None


def _absolute_parameter_refusal(
    parameters: CMJEventDetectorParameters,
    *,
    claim: str,
    observation_ids: tuple[InstanceIdentifier, ...],
) -> RefusalResult | None:
    if parameters.threshold_n is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit threshold_n",),
            observation_ids=observation_ids,
        )
    if _has_baseline_parameters(parameters):
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_PARAMETER_MISMATCH,),
            ("absolute threshold parameters without baseline-SD parameters",),
            observation_ids=observation_ids,
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    return None


def _candidate_runs(
    samples: tuple[float, ...],
    *,
    start_index: int,
    threshold_n: float,
    direction: CMJThresholdDirection,
    dwell_samples: int,
) -> tuple[tuple[tuple[int, int], ...], bool]:
    """Return qualifying contiguous runs and whether any sample crossed."""

    runs: list[tuple[int, int]] = []
    any_crossing = False
    index = start_index
    while index < len(samples):
        qualifies = (
            samples[index] < threshold_n
            if direction is CMJThresholdDirection.BELOW_THRESHOLD
            else samples[index] > threshold_n
        )
        if not qualifies:
            index += 1
            continue
        any_crossing = True
        run_start = index
        index += 1
        while index < len(samples):
            next_qualifies = (
                samples[index] < threshold_n
                if direction is CMJThresholdDirection.BELOW_THRESHOLD
                else samples[index] > threshold_n
            )
            if not next_qualifies:
                break
            index += 1
        if index - run_start >= dwell_samples:
            runs.append((run_start, index))
    return tuple(runs), any_crossing


def _event_time(timebase: SignalTimebase, sample_index: int) -> float:
    if isinstance(timebase, RegularTimebase):
        return timebase.start_time_s + sample_index / timebase.sample_rate_hz
    if isinstance(timebase, ExplicitTimebase):
        return timebase.times_s[sample_index]
    raise ValueError("event requires a registered regular or explicit timebase")


def _unique_instances(values: tuple[InstanceIdentifier, ...]) -> tuple[InstanceIdentifier, ...]:
    result: list[InstanceIdentifier] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _event_processing_parameters(
    method: CMJEventDetectorMethod,
    parameters: CMJEventDetectorParameters,
    *,
    effective_threshold_n: float,
    sample_index_semantics: str,
    time_semantics: str,
    sample_index: int,
    preceding_event_id: InstanceIdentifier | None,
) -> tuple[MetadataEntry, ...]:
    return (
        MetadataEntry("method_version", method.version),
        MetadataEntry("event_definition", method.event_definition.reference.stable_id),
        MetadataEntry("detector_parameters", canonical_json(parameters)),
        MetadataEntry("effective_threshold_n", effective_threshold_n),
        MetadataEntry("sample_index_semantics", sample_index_semantics),
        MetadataEntry("time_semantics", time_semantics),
        MetadataEntry("selected_sample_index", sample_index),
        MetadataEntry("dwell_semantics", "first sample of earliest qualifying contiguous run"),
        MetadataEntry("filtering", "none"),
        MetadataEntry("interpolation", "none"),
        MetadataEntry(
            "preceding_event_id",
            preceding_event_id.qualified if preceding_event_id is not None else None,
        ),
    )


def _event_provenance(
    force: CMJForceInput,
    baseline: SystemWeightResult | None,
    *,
    occurrence_id: InstanceIdentifier,
    method: CMJEventDetectorMethod,
    parameters: CMJEventDetectorParameters,
    effective_threshold_n: float,
    sample_index: int,
    signal: object,
    preceding_event_id: InstanceIdentifier | None,
) -> Provenance:
    if not isinstance(signal, RegularTimebase | ExplicitTimebase):
        raise ValueError("event provenance requires a registered timebase")
    base = force.observation.provenance
    source_observation_ids: tuple[InstanceIdentifier, ...] = (force.observation.observation_id,)
    if baseline is not None:
        base = _merge_provenance(base, baseline.observation.provenance)
        source_observation_ids += (baseline.observation.observation_id,)
    source_observation_ids = _unique_instances(source_observation_ids)
    source_artifact_ids = tuple(
        sorted(
            {artifact.artifact_id for artifact in base.source_artifacts}
            | {force.source_artifact.artifact_id},
            key=lambda item: item.qualified,
        )
    )
    source_acquisition_ids = tuple(
        sorted(
            {acquisition.acquisition_id for acquisition in base.acquisitions}
            | {force.acquisition.acquisition_id},
            key=lambda item: item.qualified,
        )
    )
    sample_index_semantics = "first sample of earliest qualifying contiguous dwell run"
    time_semantics = (
        "regular start_time_s + sample_index / sample_rate_hz"
        if isinstance(signal, RegularTimebase)
        else "exact explicit times_s[sample_index]"
    )
    processing_parameters = _event_processing_parameters(
        method,
        parameters,
        effective_threshold_n=effective_threshold_n,
        sample_index_semantics=sample_index_semantics,
        time_semantics=time_semantics,
        sample_index=sample_index,
        preceding_event_id=preceding_event_id,
    )
    run_digest = canonical_hash(
        {
            "occurrence_id": occurrence_id.qualified,
            "method": method.reference.stable_id,
            "parameters": parameters,
            "sample_index": sample_index,
        }
    ).removeprefix("sha256:")[:24]
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"cmj-event:{run_digest}"),
        source_artifact_ids=source_artifact_ids,
        method=method.reference,
        parameters=processing_parameters,
        software_version=RES36_SOFTWARE_VERSION,
        output_observation_id=occurrence_id,
    )
    evidence_reference = EvidenceReference(
        reference=method.decision_reference,
        applicability_note="registered RES-36 event method decision",
    )
    if evidence_reference not in base.evidence_references:
        base = replace(
            base,
            evidence_references=(*base.evidence_references, evidence_reference),
        )
    return _provenance_with_run(
        base,
        processing_run=processing_run,
        output_observation_id=occurrence_id,
        source_observation_ids=source_observation_ids,
        source_acquisition_ids=source_acquisition_ids,
        supported_by=(method.decision_reference, RES36_DECISION_EVENT_SEMANTICS),
        recorded_at=base.recorded_at,
    )


def _make_occurrence(
    force: CMJForceInput,
    baseline: SystemWeightResult | None,
    *,
    method: CMJEventDetectorMethod,
    parameters: CMJEventDetectorParameters,
    sample_index: int,
    effective_threshold_n: float,
    qc_codes: tuple[CMJEventQCCode, ...],
    preceding_event_id: InstanceIdentifier | None,
) -> CMJEventOccurrence:
    timebase = force.signal.timebase
    if timebase is None:
        raise ValueError("event occurrence requires a registered timebase")
    event_time_s = _event_time(timebase, sample_index)
    digest = canonical_hash(
        {
            "definition": method.event_definition.reference.stable_id,
            "method": method.reference.stable_id,
            "parameters": parameters,
            "source_observation": force.observation.observation_id.qualified,
            "source_signal": force.signal.signal_id.qualified,
            "sample_index": sample_index,
            "effective_threshold_n": effective_threshold_n,
        }
    ).removeprefix("sha256:")[:24]
    occurrence_id = InstanceIdentifier(
        "event-occurrence", f"cmj-{method.event_definition.label.value.casefold()}:{digest}"
    )
    provenance = _event_provenance(
        force,
        baseline,
        occurrence_id=occurrence_id,
        method=method,
        parameters=parameters,
        effective_threshold_n=effective_threshold_n,
        sample_index=sample_index,
        signal=timebase,
        preceding_event_id=preceding_event_id,
    )
    return CMJEventOccurrence(
        occurrence_id=occurrence_id,
        definition=method.event_definition,
        source_observation_id=force.observation.observation_id,
        source_signal_id=force.signal.signal_id,
        source_artifact_id=force.source_artifact.artifact_id,
        source_acquisition_id=force.acquisition.acquisition_id,
        source_measurement_identity=force.identity,
        source_timebase=timebase,
        detector_method=method,
        detector_parameters=parameters,
        sample_index=sample_index,
        event_time_s=event_time_s,
        effective_threshold_n=effective_threshold_n,
        status=CMJEventOccurrenceStatus.DETECTED,
        qc_codes=qc_codes,
        decision_reference=method.decision_reference,
        provenance=provenance,
        preceding_event_id=preceding_event_id,
    )


def _detect_from_force(
    force: CMJForceInput,
    baseline: SystemWeightResult | None,
    *,
    method: CMJEventDetectorMethod,
    parameters: CMJEventDetectorParameters,
    effective_threshold_n: float,
    search_start_index: int,
    preceding_event_id: InstanceIdentifier | None,
    failure_reason: RefusalReasonCode,
    failure_claim: str,
) -> CMJEventOccurrence | RefusalResult:
    runs, any_crossing = _candidate_runs(
        force.signal.samples,
        start_index=search_start_index,
        threshold_n=effective_threshold_n,
        direction=parameters.direction or CMJThresholdDirection.BELOW_THRESHOLD,
        dwell_samples=parameters.dwell_samples or 1,
    )
    observation_ids = _force_observation_ids(force)
    if not runs:
        reason = (
            RefusalReasonCode.INSUFFICIENT_DWELL
            if any_crossing
            else RefusalReasonCode.THRESHOLD_NOT_CROSSED
        )
        return _event_refusal(
            failure_claim,
            (failure_reason, reason),
            (
                "a qualifying threshold crossing"
                if not any_crossing
                else "a threshold crossing persisting for the configured dwell_samples",
            ),
            observation_ids=observation_ids,
        )
    selected_start, selected_end = runs[0]
    qc_codes: list[CMJEventQCCode] = []
    if len(runs) > 1:
        qc_codes.append(CMJEventQCCode.MULTIPLE_CANDIDATE_CROSSINGS)
    if selected_start == search_start_index or selected_end == len(force.signal.samples):
        qc_codes.append(CMJEventQCCode.EVENT_NEAR_SIGNAL_BOUNDARY)
    return _make_occurrence(
        force,
        baseline,
        method=method,
        parameters=parameters,
        sample_index=selected_start,
        effective_threshold_n=effective_threshold_n,
        qc_codes=tuple(qc_codes),
        preceding_event_id=preceding_event_id,
    )


def detect_movement_onset(
    force: CMJForceInput | TotalSupportedForceResult,
    baseline: SystemWeightResult | None,
    parameters: CMJEventDetectorParameters,
    *,
    method: CMJEventDetectorMethod = CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD,
) -> CMJEventOccurrence | RefusalResult:
    """Detect movement onset using the exact RES-35 force baseline/QC."""

    claim = "detect CMJ movement onset"
    prepared = _force_input_for_events(force, claim)
    if isinstance(prepared, RefusalResult):
        return prepared
    observation_ids = _force_observation_ids(prepared)
    method_refusal = _method_refusal(
        method, CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD, claim, observation_ids
    )
    if method_refusal is not None:
        return method_refusal
    parameter_refusal = _common_parameter_refusal(
        parameters,
        expected_direction=CMJThresholdDirection.BELOW_THRESHOLD,
        search_start_required=True,
        claim=claim,
        observation_ids=observation_ids,
    )
    if parameter_refusal is not None:
        return parameter_refusal
    baseline_refusal = _validate_onset_baseline(prepared, baseline, parameters, claim)
    if baseline_refusal is not None:
        return baseline_refusal
    if baseline is None or parameters.sigma_multiplier is None:
        return _baseline_refusal(claim, observation_ids, "validated onset baseline and multiplier")
    effective_threshold_n = (
        baseline.qc.mean_force_n - parameters.sigma_multiplier * baseline.qc.standard_deviation_n
    )
    return _detect_from_force(
        prepared,
        baseline,
        method=method,
        parameters=parameters,
        effective_threshold_n=effective_threshold_n,
        search_start_index=parameters.search_start_index or 0,
        preceding_event_id=None,
        failure_reason=RefusalReasonCode.THRESHOLD_NOT_CROSSED,
        failure_claim=claim,
    )


def _validate_preceding_event(
    force: CMJForceInput,
    occurrence: CMJEventOccurrence,
    *,
    expected_label: CMJEventLabel,
    claim: str,
) -> RefusalResult | None:
    if occurrence.definition.label is not expected_label:
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_DEFINITION_MISMATCH,),
            (expected_label.value,),
            observation_ids=(*_force_observation_ids(force), occurrence.source_observation_id),
            refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
        )
    if (
        occurrence.source_observation_id != force.observation.observation_id
        or occurrence.source_signal_id != force.signal.signal_id
        or occurrence.source_artifact_id != force.source_artifact.artifact_id
        or occurrence.source_acquisition_id != force.acquisition.acquisition_id
        or occurrence.source_measurement_identity != force.identity
    ):
        return _event_refusal(
            claim,
            (RefusalReasonCode.EVENT_ORDER_INVALID,),
            ("preceding event from the exact source force observation",),
            observation_ids=(*_force_observation_ids(force), occurrence.source_observation_id),
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
        )
    return None


def detect_takeoff(
    force: CMJForceInput | TotalSupportedForceResult,
    parameters: CMJEventDetectorParameters,
    *,
    onset: CMJEventOccurrence | None = None,
    method: CMJEventDetectorMethod = CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
) -> CMJEventOccurrence | RefusalResult:
    """Detect contact loss with an explicit absolute-force threshold."""

    claim = "detect CMJ takeoff/contact loss"
    prepared = _force_input_for_events(force, claim)
    if isinstance(prepared, RefusalResult):
        return prepared
    observation_ids = _force_observation_ids(prepared)
    method_refusal = _method_refusal(
        method, CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD, claim, observation_ids
    )
    if method_refusal is not None:
        return method_refusal
    parameter_refusal = _common_parameter_refusal(
        parameters,
        expected_direction=CMJThresholdDirection.BELOW_THRESHOLD,
        search_start_required=True,
        claim=claim,
        observation_ids=observation_ids,
    )
    if parameter_refusal is not None:
        return parameter_refusal
    absolute_refusal = _absolute_parameter_refusal(
        parameters,
        claim=claim,
        observation_ids=observation_ids,
    )
    if absolute_refusal is not None:
        return absolute_refusal
    if parameters.search_start_index is None or parameters.threshold_n is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit takeoff threshold and search start",),
            observation_ids=observation_ids,
        )
    if parameters.search_start_index >= len(prepared.signal.samples):
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("takeoff search_start_index inside source sample support",),
            observation_ids=observation_ids,
        )
    if onset is not None:
        onset_refusal = _validate_preceding_event(
            prepared,
            onset,
            expected_label=CMJEventLabel.MOVEMENT_ONSET,
            claim=claim,
        )
        if onset_refusal is not None:
            return onset_refusal
        if parameters.search_start_index <= onset.sample_index:
            return _event_refusal(
                claim,
                (RefusalReasonCode.EVENT_ORDER_INVALID,),
                ("takeoff search_start_index strictly after movement-onset sample_index",),
                observation_ids=(*observation_ids, onset.source_observation_id),
                refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
            )
    return _detect_from_force(
        prepared,
        None,
        method=method,
        parameters=parameters,
        effective_threshold_n=parameters.threshold_n,
        search_start_index=parameters.search_start_index,
        preceding_event_id=onset.occurrence_id if onset is not None else None,
        failure_reason=RefusalReasonCode.TAKEOFF_NOT_FOUND,
        failure_claim=claim,
    )


def detect_landing(
    force: CMJForceInput | TotalSupportedForceResult,
    takeoff: CMJEventOccurrence,
    parameters: CMJEventDetectorParameters,
    *,
    method: CMJEventDetectorMethod = CMJ_LANDING_ABSOLUTE_FORCE_METHOD,
) -> CMJEventOccurrence | RefusalResult:
    """Detect contact regain only after a valid takeoff occurrence."""

    claim = "detect CMJ landing/contact regain"
    prepared = _force_input_for_events(force, claim)
    if isinstance(prepared, RefusalResult):
        return prepared
    observation_ids = _force_observation_ids(prepared)
    method_refusal = _method_refusal(
        method, CMJ_LANDING_ABSOLUTE_FORCE_METHOD, claim, observation_ids
    )
    if method_refusal is not None:
        return method_refusal
    parameter_refusal = _common_parameter_refusal(
        parameters,
        expected_direction=CMJThresholdDirection.ABOVE_THRESHOLD,
        search_start_required=False,
        claim=claim,
        observation_ids=observation_ids,
    )
    if parameter_refusal is not None:
        return parameter_refusal
    absolute_refusal = _absolute_parameter_refusal(
        parameters,
        claim=claim,
        observation_ids=observation_ids,
    )
    if absolute_refusal is not None:
        return absolute_refusal
    takeoff_refusal = _validate_preceding_event(
        prepared,
        takeoff,
        expected_label=CMJEventLabel.TAKEOFF_CONTACT_LOSS,
        claim=claim,
    )
    if takeoff_refusal is not None:
        return takeoff_refusal
    if parameters.threshold_n is None:
        return _event_refusal(
            claim,
            (RefusalReasonCode.THRESHOLD_PARAMETER_MISSING,),
            ("explicit landing threshold_n",),
            observation_ids=observation_ids,
        )
    search_start_index = takeoff.sample_index + 1
    if search_start_index >= len(prepared.signal.samples):
        return _event_refusal(
            claim,
            (RefusalReasonCode.LANDING_NOT_FOUND, RefusalReasonCode.THRESHOLD_NOT_CROSSED),
            ("sample support after takeoff for landing search",),
            observation_ids=(*observation_ids, takeoff.source_observation_id),
        )
    return _detect_from_force(
        prepared,
        None,
        method=method,
        parameters=parameters,
        effective_threshold_n=parameters.threshold_n,
        search_start_index=search_start_index,
        preceding_event_id=takeoff.occurrence_id,
        failure_reason=RefusalReasonCode.LANDING_NOT_FOUND,
        failure_claim=claim,
    )


def validate_cmj_event_order(
    occurrences: tuple[CMJEventOccurrence, ...],
) -> RefusalResult | None:
    """Validate supplied event order without sorting or repairing it."""

    require_tuple(occurrences, "occurrences")
    if len(occurrences) < 2:
        return None
    ranks = {
        CMJEventLabel.MOVEMENT_ONSET: 0,
        CMJEventLabel.TAKEOFF_CONTACT_LOSS: 1,
        CMJEventLabel.LANDING_CONTACT_REGAIN: 2,
    }
    observation_ids = tuple(item.source_observation_id for item in occurrences)
    seen: set[CMJEventLabel] = set()
    previous_rank = -1
    previous_index = -1
    previous_time = -math.inf
    source = occurrences[0]
    for occurrence in occurrences:
        label = occurrence.definition.label
        if (
            label not in ranks
            or label in seen
            or occurrence.source_observation_id != source.source_observation_id
            or occurrence.source_signal_id != source.source_signal_id
            or occurrence.sample_index <= previous_index
            or occurrence.event_time_s <= previous_time
            or ranks[label] <= previous_rank
        ):
            return _event_refusal(
                "validate CMJ event ordering",
                (RefusalReasonCode.EVENT_ORDER_INVALID,),
                ("MOVEMENT_ONSET < TAKEOFF_CONTACT_LOSS < LANDING_CONTACT_REGAIN",),
                observation_ids=observation_ids,
                refusal_class=RefusalClass.ANALYSIS_DESIGN_MISMATCH,
            )
        seen.add(label)
        previous_rank = ranks[label]
        previous_index = occurrence.sample_index
        previous_time = occurrence.event_time_s
    return None


def _event_parameter_key(parameters: CMJEventDetectorParameters) -> tuple[object, ...]:
    segment = parameters.baseline_segment
    segment_key: tuple[object, ...] | None = None
    if segment is not None:
        segment_key = (
            segment.selection_method.stable_id,
            segment.start_index,
            segment.end_index,
            segment.selection_parameters,
        )
    return (
        parameters.threshold_n,
        segment_key,
        parameters.baseline_mean_force_n,
        parameters.baseline_standard_deviation_n,
        parameters.sigma_multiplier,
        parameters.direction.value if parameters.direction is not None else None,
        parameters.dwell_samples,
        parameters.search_start_index,
    )


def _timebase_key(timebase: SignalTimebase) -> tuple[object, ...]:
    if isinstance(timebase, RegularTimebase):
        return ("REGULAR", timebase.sample_rate_hz)
    if isinstance(timebase, ExplicitTimebase):
        if not timebase.times_s:
            return ("EXPLICIT", ())
        origin = timebase.times_s[0]
        return ("EXPLICIT", tuple(time - origin for time in timebase.times_s))
    return ("UNKNOWN",)


def _processing_key(identity: CMJMeasurementIdentity) -> tuple[object, ...]:
    processing = identity.processing
    ignored = frozenset(
        {
            "source_signal_id",
            "source_artifact_id",
            "source_measurement_identity_id",
            "left_source_signal_id",
            "right_source_signal_id",
        }
    )
    parameters = tuple(
        (entry.key, entry.value)
        for entry in processing.method_parameters
        if entry.key not in ignored
    )
    return (
        processing.registered_operation.stable_id
        if processing.registered_operation is not None
        else None,
        processing.estimator.stable_id if processing.estimator is not None else None,
        parameters,
        processing.filtering,
        processing.differentiation_method,
        processing.integration_method,
        processing.unit,
        processing.sign_convention,
        processing.event_definitions,
        processing.phase_definitions,
        processing.normalization,
        processing.trial_selection,
        processing.aggregation,
        identity.version,
    )


def _comparability_result(
    request: CMJEventComparabilityRequest,
    *,
    state: ComparabilityState,
    reason_codes: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    transformations_required: tuple[TransformationRequest, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=reason_codes,
        conditions=conditions,
        transformations_required=transformations_required,
        missing_information=missing_information,
        rule_reference=CMJ_EVENT_COMPARABILITY_RULE,
        evidence_references=(RES36_DECISION_EVENT_SEMANTICS,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def assess_cmj_event_comparability(
    request: CMJEventComparabilityRequest,
    left: CMJEventOccurrence,
    right: CMJEventOccurrence,
) -> ComparabilityResult:
    """Compare event definitions, methods, parameters, and source identity."""

    differences: list[tuple[str, str]] = []
    if left.definition != right.definition:
        differences.append((ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH, "event_definition"))
    if left.detector_method != right.detector_method:
        differences.append((ComparabilityReasonCode.EVENT_METHOD_MISMATCH, "event_method"))
    if (
        _event_parameter_key(left.detector_parameters)
        != _event_parameter_key(right.detector_parameters)
        or left.effective_threshold_n != right.effective_threshold_n
    ):
        differences.append((ComparabilityReasonCode.EVENT_PARAMETER_MISMATCH, "event_parameters"))

    if left.source_observation_id == right.source_observation_id:
        source_result = None
        if left.source_measurement_identity != right.source_measurement_identity:
            differences.append(
                (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, "source_identity")
            )
    else:
        source_request = CMJComparabilityRequest(
            request_id=InstanceIdentifier(
                "comparability-request", f"{request.request_id.value}:source"
            ),
            left_observation_id=left.source_observation_id,
            right_observation_id=right.source_observation_id,
            left_identity=left.source_measurement_identity,
            right_identity=right.source_measurement_identity,
            claim=request.claim,
        )
        source_result = assess_cmj_acquisition_comparability(source_request)
    if (
        source_result is not None
        and source_result.state is ComparabilityState.INSUFFICIENT_INFORMATION
    ):
        missing = tuple(dict.fromkeys(source_result.missing_information))
        return ComparabilityResult(
            result_id=InstanceIdentifier(
                "comparability-result", f"{request.request_id.value}:insufficient-information"
            ),
            request_id=request.request_id,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reason_codes=(
                ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,
                ComparabilityReasonCode.MISSING_METADATA,
            ),
            conditions=(),
            transformations_required=request.requested_transformations,
            missing_information=missing or ("complete source acquisition identity",),
            rule_reference=None,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.UNRESOLVED,
        )
    if source_result is not None and source_result.state is not ComparabilityState.COMPARABLE:
        differences.extend(
            (reason_code, f"source_{reason_code.casefold()}")
            for reason_code in source_result.reason_codes
            if reason_code != ComparabilityReasonCode.BRIDGE_NOT_REGISTERED
        )
    if _processing_key(left.source_measurement_identity) != _processing_key(
        right.source_measurement_identity
    ):
        differences.append(
            (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH, "source_processing")
        )
    if _timebase_key(left.source_timebase) != _timebase_key(right.source_timebase):
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "signal_timebase"))

    if request.requested_transformations and not differences:
        return _comparability_result(
            request,
            state=ComparabilityState.REQUIRES_TRANSFORMATION,
            reason_codes=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            transformations_required=request.requested_transformations,
            conditions=("the requested registered transformation must be applied first",),
        )
    if differences:
        reason_codes = tuple(
            dict.fromkeys(
                (
                    ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,
                    *(reason for reason, _ in differences),
                )
            )
        )
        return _comparability_result(
            request,
            state=ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            reason_codes=reason_codes,
            conditions=(
                "a registered deterministic event/method/source bridge is required before "
                "the claim",
            ),
            transformations_required=request.requested_transformations,
        )
    return _comparability_result(request, state=ComparabilityState.COMPARABLE)


def compare_cmj_events(
    left: CMJEventOccurrence,
    right: CMJEventOccurrence,
    *,
    claim: str,
    request_id: InstanceIdentifier,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Convenience constructor for claim-relative event comparison."""

    return assess_cmj_event_comparability(
        CMJEventComparabilityRequest(
            request_id=request_id,
            left_event_id=left.occurrence_id,
            right_event_id=right.occurrence_id,
            claim=claim,
            requested_transformations=requested_transformations,
        ),
        left,
        right,
    )


def refusal_for_cmj_event_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Map an event comparison limitation to the existing refusal architecture."""

    from dynamislm.measurement.cmj.refusal import refusal_for_cmj_event_comparability as _refuse

    return _refuse(result, blocked_claim=blocked_claim, observation_ids=observation_ids)


__all__ = [
    "CMJ_LANDING_ABSOLUTE_FORCE_METHOD",
    "CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION",
    "CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD",
    "CMJ_MOVEMENT_ONSET_EVENT_DEFINITION",
    "CMJ_REGISTERED_EVENT_METHODS",
    "CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD",
    "CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION",
    "RES36_SOFTWARE_VERSION",
    "CMJEventComparabilityRequest",
    "CMJEventDefinition",
    "CMJEventDetectorMethod",
    "CMJEventDetectorParameters",
    "CMJEventLabel",
    "CMJEventOccurrence",
    "CMJEventOccurrenceStatus",
    "CMJEventQCCode",
    "CMJEventThresholdFamily",
    "CMJThresholdDirection",
    "assess_cmj_event_comparability",
    "compare_cmj_events",
    "detect_landing",
    "detect_movement_onset",
    "detect_takeoff",
    "refusal_for_cmj_event_comparability",
    "validate_cmj_event_order",
]
