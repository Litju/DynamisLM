"""Immutable RES-69 statistical support, authority, and result contracts.

The statistical layer deliberately composes the RES-62 observation and
multi-source contracts.  It does not introduce another longitudinal record
model and it never stores a naked tuple of numbers as scientific authority.
"""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, cast

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    MultiSourceAnalysisInput,
    MultiSourceProcessingRun,
    MultiSourceProvenanceGraph,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    NormalizationSpec,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.provenance.models import EvidenceReference
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256_PREFIX = "sha256:"


def _require_hash(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    digest = value.removeprefix(_SHA256_PREFIX)
    if (
        not value.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a canonical sha256 hash")


def _require_identifier(
    value: object,
    expected_type: str,
    field_name: str,
) -> InstanceIdentifier:
    _require_instance(value, InstanceIdentifier, field_name)
    assert isinstance(value, InstanceIdentifier)
    if value.instance_type != expected_type:
        raise ValueError(f"{field_name} must identify a {expected_type}")
    return value


def _require_scientific_identifier(value: object, field_name: str) -> ScientificIdentifier:
    try:
        return _stable_identifier(value, field_name)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a ScientificIdentifier-compatible identity"
        ) from exc


def _stable_identifier(value: object, field_name: str) -> ScientificIdentifier:
    if isinstance(value, ScientificIdentifier):
        return value
    if isinstance(value, RegistryReference):
        return value.identifier
    if isinstance(value, UnitReference):
        return value.identifier
    if isinstance(value, MeasurementIdentity):
        return value.identity_id
    raise ValueError(
        f"{field_name} must be a ScientificIdentifier, RegistryReference, UnitReference, "
        "or MeasurementIdentity"
    )


def _require_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")


def _require_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _require_datetime(value: object, field_name: str) -> datetime_module.datetime:
    if not isinstance(value, datetime_module.datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")
    return value


class StatisticalSupportWindowKind(StrEnum):
    FULL_SUPPORT = "FULL_SUPPORT"
    COUNT_WINDOW = "COUNT_WINDOW"
    TIME_WINDOW = "TIME_WINDOW"


class MissingnessPolicy(StrEnum):
    """V1 missingness policy; none of these policies imply imputation."""

    COMPLETE_CASE_ONLY = "COMPLETE_CASE_ONLY"
    EXPLICIT_EXCLUSION_ONLY = "EXPLICIT_EXCLUSION_ONLY"
    NO_IMPUTATION_NO_ZERO_FILL = "NO_IMPUTATION_NO_ZERO_FILL"


class SupportExclusionReason(StrEnum):
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    NOT_SELECTED = "NOT_SELECTED"
    INVALID_RESULT = "INVALID_RESULT"
    MISSING_VALUE = "MISSING_VALUE"
    INCOMPATIBLE_IDENTITY = "INCOMPATIBLE_IDENTITY"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"


class SupportSelectionStatus(StrEnum):
    EXCLUDED = "EXCLUDED"


class MeasurementScaleKind(StrEnum):
    RATIO = "RATIO"
    INTERVAL = "INTERVAL"
    ORDINAL = "ORDINAL"
    NOMINAL = "NOMINAL"
    UNKNOWN = "UNKNOWN"


class SignedValuePolicy(StrEnum):
    SIGNED = "SIGNED"
    NONNEGATIVE = "NONNEGATIVE"
    STRICTLY_POSITIVE = "STRICTLY_POSITIVE"


class DenominatorPolicy(StrEnum):
    NONZERO = "NONZERO"
    STRICTLY_POSITIVE = "STRICTLY_POSITIVE"


class ScaleAuthorityOrigin(StrEnum):
    PRODUCTION = "PRODUCTION"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class ReliabilityQuestion(StrEnum):
    REPEATABILITY = "REPEATABILITY"
    REPRODUCIBILITY = "REPRODUCIBILITY"


class StableUnderlyingQuantityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNRESOLVED = "UNRESOLVED"


class SystematicTrialEffectStatus(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    NO_EVIDENCE_OF_SYSTEMATIC_EFFECT = "NO_EVIDENCE_OF_SYSTEMATIC_EFFECT"
    SYSTEMATIC_EFFECT_PRESENT = "SYSTEMATIC_EFFECT_PRESENT"
    UNRESOLVED = "UNRESOLVED"


class ReliabilityErrorScale(StrEnum):
    RAW_ABSOLUTE = "RAW_ABSOLUTE"
    RAW_RELATIVE = "RAW_RELATIVE"
    LOG_MULTIPLICATIVE = "LOG_MULTIPLICATIVE"


class AuthorityStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    SOURCE_BOUND = "SOURCE_BOUND"


class RepeatedPairPolicy(StrEnum):
    ONE_PAIR_PER_INDEPENDENT_SUBJECT = "ONE_PAIR_PER_INDEPENDENT_SUBJECT"


class StatisticalOperationDisposition(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    REPRESENT_BUT_DO_NOT_COMPUTE = "REPRESENT_BUT_DO_NOT_COMPUTE"
    DEFER = "DEFER"
    REJECT = "REJECT"


class RES69ReasonCode(StrEnum):
    """Operation-local granular refusal reasons; generic refusal classes stay unchanged."""

    IDENTITY_UNRESOLVED = "RES69_IDENTITY_UNRESOLVED"
    COMPARABILITY_UNESTABLISHED = "RES69_COMPARABILITY_UNESTABLISHED"
    SCALE_SEMANTICS_UNREGISTERED = "RES69_SCALE_SEMANTICS_UNREGISTERED"
    SCALE_OPERATION_NOT_AUTHORIZED = "RES69_SCALE_OPERATION_NOT_AUTHORIZED"
    UNIT_MISMATCH = "RES69_UNIT_MISMATCH"
    UNIT_CONVERSION_NOT_REGISTERED = "RES69_UNIT_CONVERSION_NOT_REGISTERED"
    DATA_ADEQUACY_INSUFFICIENT = "RES69_DATA_ADEQUACY_INSUFFICIENT"
    ANALYSIS_DESIGN_MISMATCH = "RES69_ANALYSIS_DESIGN_MISMATCH"
    RELIABILITY_AUTHORITY_REQUIRED = "RES69_RELIABILITY_AUTHORITY_REQUIRED"
    METHOD_COMPARISON_AUTHORITY_REQUIRED = "RES69_METHOD_COMPARISON_AUTHORITY_REQUIRED"
    SUPPORT_MISMATCH = "RES69_SUPPORT_MISMATCH"
    INCOMPLETE_PAIR = "RES69_INCOMPLETE_PAIR"
    UNBALANCED_RELIABILITY_SUPPORT = "RES69_UNBALANCED_RELIABILITY_SUPPORT"
    NONPOSITIVE_LOG_INPUT = "RES69_NONPOSITIVE_LOG_INPUT"
    ZERO_REFERENCE_SD = "RES69_ZERO_REFERENCE_SD"
    DUPLICATE_TIMESTAMP = "RES69_DUPLICATE_TIMESTAMP"
    OPERATION_NOT_REGISTERED = "RES69_OPERATION_NOT_REGISTERED"
    CLASSICAL_LOA_DEFERRED = "RES69_CLASSICAL_LOA_DEFERRED"
    INTERPRETATION_NOT_AUTHORIZED = "RES69_INTERPRETATION_NOT_AUTHORIZED"
    REGISTRY_INTEGRITY_FAILURE = "RES69_REGISTRY_INTEGRITY_FAILURE"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DerivedUnitReference:
    """Deterministic composite unit without changing core UnitReference semantics."""

    numerator: UnitReference
    denominator: UnitReference
    operation: RegistryReference
    display_label: str

    def __post_init__(self) -> None:
        _require_instance(self.numerator, UnitReference, "numerator")
        _require_instance(self.denominator, UnitReference, "denominator")
        _require_instance(self.operation, RegistryReference, "operation")
        if self.operation.identifier.object_type != "unit-derivation":
            raise ValueError("operation must identify a registered unit derivation")
        _require_text(self.display_label, "display_label")

    @property
    def stable_id(self) -> str:
        return (
            f"{self.operation.stable_id}:"
            f"{self.numerator.identifier.stable_id}/"
            f"{self.denominator.identifier.stable_id}"
        )


type StatisticalUnitReference = UnitReference | DerivedUnitReference


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementScaleSemanticKeyV1:
    """Stable semantic dimensions used to look up scale authority.

    Instance, athlete, timestamp, session, artifact, acquisition, and
    processing-run identities are intentionally absent from this key.
    """

    construct_id: ScientificIdentifier
    test_family_id: ScientificIdentifier
    measurand_id: ScientificIdentifier
    metric_definition_id: ScientificIdentifier
    unit_id: ScientificIdentifier
    normalization_identity: NormalizationSpec | None
    registered_operation_identity: ScientificIdentifier | None
    estimator_identity: ScientificIdentifier | None
    protocol_constraint: ScientificIdentifier | None = None
    scale_relevant_method_parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "construct_id",
            "test_family_id",
            "measurand_id",
            "metric_definition_id",
            "unit_id",
        ):
            value = _stable_identifier(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)
        for field_name in (
            "registered_operation_identity",
            "estimator_identity",
            "protocol_constraint",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _stable_identifier(value, field_name))
        if self.unit_id.object_type != "unit":
            raise ValueError("unit_id must identify a registered unit")
        if self.normalization_identity is not None and not isinstance(
            self.normalization_identity,
            NormalizationSpec,
        ):
            raise ValueError("normalization_identity must be a NormalizationSpec")
        _require_tuple_items(
            self.scale_relevant_method_parameters,
            MetadataEntry,
            "scale_relevant_method_parameters",
        )

    @classmethod
    def from_measurement_identity(
        cls,
        identity: MeasurementIdentity,
        unit: UnitReference,
        *,
        scale_relevant_method_parameters: tuple[MetadataEntry, ...] | None = None,
        protocol_constraint: RegistryReference | ScientificIdentifier | None = None,
    ) -> MeasurementScaleSemanticKeyV1:
        """Derive the key from identity semantics, never from identity_id."""

        if not isinstance(identity, MeasurementIdentity):
            raise ValueError("identity must be a MeasurementIdentity")
        if not isinstance(unit, UnitReference):
            raise ValueError("unit must be a UnitReference")
        parameters = (
            () if scale_relevant_method_parameters is None else scale_relevant_method_parameters
        )
        registered_operation = identity.processing.registered_operation
        estimator = identity.processing.estimator
        protocol = protocol_constraint
        return cls(
            construct_id=identity.semantic.construct.identifier,
            test_family_id=identity.semantic.test_family.identifier,
            measurand_id=identity.semantic.measurand.identifier,
            metric_definition_id=identity.semantic.metric_definition.identifier,
            unit_id=unit.identifier,
            normalization_identity=identity.processing.normalization,
            registered_operation_identity=(
                registered_operation.identifier if registered_operation is not None else None
            ),
            estimator_identity=estimator.identifier if estimator is not None else None,
            protocol_constraint=(
                _stable_identifier(protocol, "protocol_constraint")
                if protocol is not None
                else None
            ),
            scale_relevant_method_parameters=parameters,
        )

    from_identity = from_measurement_identity

    @property
    def stable_key(self) -> str:
        return canonical_hash(self)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementScaleSemantics:
    """Registered scale authority; a standalone instance is not authority."""

    semantic_key: MeasurementScaleSemanticKeyV1
    scale_kind: MeasurementScaleKind
    meaningful_zero: bool
    signed_value_policy: SignedValuePolicy
    denominator_policy: DenominatorPolicy
    relative_change_authorized: bool
    log_ratio_authorized: bool
    raw_relative_error_authorized: bool
    log_error_authorized: bool
    authority_reference: RegistryReference
    evidence_references: tuple[EvidenceReference, ...]
    authority_origin: ScaleAuthorityOrigin
    rationale: str

    def __post_init__(self) -> None:
        _require_instance(self.semantic_key, MeasurementScaleSemanticKeyV1, "semantic_key")
        _require_enum(self.scale_kind, MeasurementScaleKind, "scale_kind")
        _require_bool(self.meaningful_zero, "meaningful_zero")
        _require_enum(self.signed_value_policy, SignedValuePolicy, "signed_value_policy")
        _require_enum(self.denominator_policy, DenominatorPolicy, "denominator_policy")
        for field_name in (
            "relative_change_authorized",
            "log_ratio_authorized",
            "raw_relative_error_authorized",
            "log_error_authorized",
        ):
            _require_bool(getattr(self, field_name), field_name)
        if (
            self.relative_change_authorized or self.raw_relative_error_authorized
        ) and self.scale_kind is not MeasurementScaleKind.RATIO:
            raise ValueError("relative arithmetic requires registered ratio-scale semantics")
        if self.log_ratio_authorized or self.log_error_authorized:
            if self.scale_kind is not MeasurementScaleKind.RATIO:
                raise ValueError("log arithmetic requires registered ratio-scale semantics")
            if self.signed_value_policy is not SignedValuePolicy.STRICTLY_POSITIVE:
                raise ValueError("log arithmetic requires a strictly-positive value policy")
        _require_instance(self.authority_reference, RegistryReference, "authority_reference")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        if not self.evidence_references:
            raise ValueError("scale semantics require evidence references")
        _require_enum(self.authority_origin, ScaleAuthorityOrigin, "authority_origin")
        _require_text(self.rationale, "rationale")

    @property
    def scale_key(self) -> MeasurementScaleSemanticKeyV1:
        return self.semantic_key

    @property
    def relative_change_allowed(self) -> bool:
        return self.relative_change_authorized

    @property
    def log_ratio_allowed(self) -> bool:
        return self.log_ratio_authorized

    @property
    def raw_relative_error_allowed(self) -> bool:
        return self.raw_relative_error_authorized

    @property
    def log_error_allowed(self) -> bool:
        return self.log_error_authorized


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalSourceRecordReference:
    record_id: InstanceIdentifier
    record_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.record_id, "longitudinal-athlete-record", "record_id")
        _require_hash(self.record_hash, "record_hash")

    @classmethod
    def from_record(
        cls, record: LongitudinalAthletePerformanceRecord
    ) -> StatisticalSourceRecordReference:
        if not isinstance(record, LongitudinalAthletePerformanceRecord):
            raise ValueError("record must be a LongitudinalAthletePerformanceRecord")
        if record.record_id is None:
            raise ValueError("record must have a canonical record ID")
        return cls(record.record_id, record.canonical_record_hash)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalSourceArtifactReference:
    artifact_id: InstanceIdentifier
    content_digest: str

    def __post_init__(self) -> None:
        _require_identifier(self.artifact_id, "artifact", "artifact_id")
        _require_text(self.content_digest, "content_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalProvenanceReference:
    provenance_id: InstanceIdentifier
    provenance_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.provenance_id, "provenance", "provenance_id")
        _require_hash(self.provenance_hash, "provenance_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalObservationReference:
    """Exact immutable reference to one RES-62 observation entry."""

    entry_id: InstanceIdentifier
    entry_hash: str
    observation_id: InstanceIdentifier
    observation_hash: str
    athlete_id: InstanceIdentifier
    session_id: InstanceIdentifier
    trial_id: InstanceIdentifier | None

    def __post_init__(self) -> None:
        _require_identifier(self.entry_id, "longitudinal-entry", "entry_id")
        _require_hash(self.entry_hash, "entry_hash")
        _require_identifier(self.observation_id, "observation", "observation_id")
        _require_hash(self.observation_hash, "observation_hash")
        _require_identifier(self.athlete_id, "athlete", "athlete_id")
        _require_identifier(self.session_id, "session", "session_id")
        _require_optional_instance(self.trial_id, InstanceIdentifier, "trial_id")
        if self.trial_id is not None and self.trial_id.instance_type != "trial":
            raise ValueError("trial_id must identify a trial")

    @classmethod
    def from_entry(cls, entry: LongitudinalObservationEntry) -> StatisticalObservationReference:
        if not isinstance(entry, LongitudinalObservationEntry):
            raise ValueError("entry must be a LongitudinalObservationEntry")
        return cls(
            entry_id=entry.canonical_entry_id,
            entry_hash=entry.canonical_entry_hash,
            observation_id=entry.source_observation_id,
            observation_hash=canonical_hash(entry.observation),
            athlete_id=entry.observation.context.athlete_id,
            session_id=entry.session_id,
            trial_id=entry.observation.context.trial_id,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SupportEntryExclusion:
    reference: StatisticalObservationReference
    reason: SupportExclusionReason
    status: SupportSelectionStatus = SupportSelectionStatus.EXCLUDED
    note: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.reference, StatisticalObservationReference, "reference")
        _require_enum(self.reason, SupportExclusionReason, "reason")
        _require_enum(self.status, SupportSelectionStatus, "status")
        if self.note is not None:
            _require_text(self.note, "note")

    @classmethod
    def from_entry(
        cls,
        entry: LongitudinalObservationEntry,
        reason: SupportExclusionReason,
        *,
        note: str | None = None,
    ) -> SupportEntryExclusion:
        return cls(StatisticalObservationReference.from_entry(entry), reason, note=note)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalWindow:
    kind: StatisticalSupportWindowKind
    start: datetime_module.datetime | None = None
    end: datetime_module.datetime | None = None
    start_inclusive: bool = True
    end_inclusive: bool = True
    count: int | None = None

    def __post_init__(self) -> None:
        _require_enum(self.kind, StatisticalSupportWindowKind, "kind")
        _require_bool(self.start_inclusive, "start_inclusive")
        _require_bool(self.end_inclusive, "end_inclusive")
        if self.start is not None:
            _require_datetime(self.start, "start")
        if self.end is not None:
            _require_datetime(self.end, "end")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("window start must not exceed window end")
        if self.kind is StatisticalSupportWindowKind.FULL_SUPPORT:
            if self.start is not None or self.end is not None or self.count is not None:
                raise ValueError("FULL_SUPPORT must not carry bounds or count")
        elif self.kind is StatisticalSupportWindowKind.COUNT_WINDOW:
            if self.count is None or isinstance(self.count, bool) or self.count < 1:
                raise ValueError("COUNT_WINDOW requires a positive count")
            if self.start is not None or self.end is not None:
                raise ValueError("COUNT_WINDOW must not carry time bounds")
        elif self.kind is StatisticalSupportWindowKind.TIME_WINDOW:
            if self.start is None or self.end is None:
                raise ValueError("TIME_WINDOW requires start and end")
            if self.count is not None:
                raise ValueError("TIME_WINDOW must not carry a count")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalComparabilityEvidence:
    request: ComparabilityRequest
    result: ComparabilityResult

    def __post_init__(self) -> None:
        _require_instance(self.request, ComparabilityRequest, "request")
        _require_instance(self.result, ComparabilityResult, "result")
        _require_identifier(
            self.request.request_id,
            "comparability-request",
            "request.request_id",
        )
        _require_identifier(
            self.request.left_observation_id,
            "observation",
            "request.left_observation_id",
        )
        _require_identifier(
            self.request.right_observation_id,
            "observation",
            "request.right_observation_id",
        )
        if self.result.request_id != self.request.request_id:
            raise ValueError("comparability evidence result must match its request")
        if self.result.state not in (
            ComparabilityState.COMPARABLE,
            ComparabilityState.COMPARABLE_WITH_CONDITIONS,
        ):
            raise ValueError("statistical support requires an affirmative comparability result")
        if self.result.rule_reference is None:
            raise ValueError("comparability evidence must identify its deterministic rule")
        if self.result.decided_by is not ComparabilityDecisionSource.DETERMINISTIC_RULE:
            raise ValueError("comparability evidence must be deterministic-rule authority")

    @property
    def pair_ids(self) -> tuple[InstanceIdentifier, InstanceIdentifier]:
        return self.request.left_observation_id, self.request.right_observation_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalSupport:
    """Exact RES-62-backed support for one or more deterministic operations."""

    analysis_inputs: tuple[MultiSourceAnalysisInput, ...]
    included_entries: tuple[LongitudinalObservationEntry, ...]
    excluded_entries: tuple[SupportEntryExclusion, ...]
    missingness_policy: MissingnessPolicy
    window: StatisticalWindow
    source_records: tuple[StatisticalSourceRecordReference, ...]
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = ()
    current_entry_id: InstanceIdentifier | None = None
    reference_entry_ids: tuple[InstanceIdentifier, ...] = ()
    support_id: InstanceIdentifier | None = None
    support_hash: str | None = None

    def __post_init__(self) -> None:
        require_tuple(self.analysis_inputs, "analysis_inputs")
        if not self.analysis_inputs:
            raise ValueError("statistical support requires at least one RES-62 analysis input")
        if any(not isinstance(item, MultiSourceAnalysisInput) for item in self.analysis_inputs):
            raise ValueError("analysis_inputs must contain MultiSourceAnalysisInput values")
        expected_inputs = tuple(
            sorted(
                self.analysis_inputs,
                key=lambda item: (item.athlete.athlete_id.qualified, item.input_id.qualified),
            )
        )
        if self.analysis_inputs != expected_inputs:
            raise ValueError("analysis_inputs must use canonical athlete/input ordering")
        require_tuple(self.included_entries, "included_entries")
        if not self.included_entries:
            raise ValueError("statistical support requires at least one included entry")
        if any(
            not isinstance(item, LongitudinalObservationEntry) for item in self.included_entries
        ):
            raise ValueError("included_entries must contain LongitudinalObservationEntry values")
        require_tuple(self.excluded_entries, "excluded_entries")
        if any(not isinstance(item, SupportEntryExclusion) for item in self.excluded_entries):
            raise ValueError("excluded_entries must contain SupportEntryExclusion values")
        expected_exclusions = tuple(
            sorted(self.excluded_entries, key=lambda item: item.reference.entry_id.qualified)
        )
        if self.excluded_entries != expected_exclusions:
            raise ValueError("excluded_entries must use canonical entry ordering")
        _require_enum(self.missingness_policy, MissingnessPolicy, "missingness_policy")
        _require_instance(self.window, StatisticalWindow, "window")
        require_tuple(self.source_records, "source_records")
        if any(
            not isinstance(item, StatisticalSourceRecordReference) for item in self.source_records
        ):
            raise ValueError("source_records must contain StatisticalSourceRecordReference values")
        require_tuple(self.comparability_evidence, "comparability_evidence")
        if any(
            not isinstance(item, StatisticalComparabilityEvidence)
            for item in self.comparability_evidence
        ):
            raise ValueError(
                "comparability_evidence must contain StatisticalComparabilityEvidence values"
            )
        _require_optional_instance(self.current_entry_id, InstanceIdentifier, "current_entry_id")
        if (
            self.current_entry_id is not None
            and self.current_entry_id.instance_type != "longitudinal-entry"
        ):
            raise ValueError("current_entry_id must identify a longitudinal entry")
        require_tuple(self.reference_entry_ids, "reference_entry_ids")
        for entry_id in self.reference_entry_ids:
            _require_identifier(entry_id, "longitudinal-entry", "reference_entry_ids item")
        _require_optional_instance(self.support_id, InstanceIdentifier, "support_id")
        if self.support_id is not None and self.support_id.instance_type != "statistical-support":
            raise ValueError("support_id must identify statistical support")
        if self.support_hash is not None:
            _require_hash(self.support_hash, "support_hash")

        input_entries: dict[str, LongitudinalObservationEntry] = {}
        input_athletes: dict[str, str] = {}
        for analysis_input in self.analysis_inputs:
            for entry in analysis_input.entries:
                key = entry.canonical_entry_id.qualified
                if key in input_entries and input_entries[key] != entry:
                    raise ValueError("analysis inputs contain conflicting entry content")
                input_entries[key] = entry
                input_athletes[key] = analysis_input.athlete.athlete_id.qualified
        included_ids = tuple(entry.canonical_entry_id.qualified for entry in self.included_entries)
        if len(set(included_ids)) != len(included_ids):
            raise ValueError("included_entries must not contain duplicate entry IDs")
        expected_order = tuple(
            sorted(
                self.included_entries,
                key=lambda entry: (
                    entry.observed_at.astimezone(datetime_module.UTC).isoformat(
                        timespec="microseconds"
                    ),
                    entry.source_observation_id.qualified,
                    entry.canonical_entry_hash,
                ),
            )
        )
        if self.included_entries != expected_order:
            raise ValueError("included_entries must use canonical temporal ordering")
        for entry in self.included_entries:
            key = entry.canonical_entry_id.qualified
            if key not in input_entries or input_entries[key] != entry:
                raise ValueError("included entry is not an exact entry of an analysis input")
        excluded_ids = tuple(item.reference.entry_id.qualified for item in self.excluded_entries)
        if len(set(excluded_ids)) != len(excluded_ids):
            raise ValueError("excluded_entries must not contain duplicate entry IDs")
        for item in self.excluded_entries:
            key = item.reference.entry_id.qualified
            matched_entry = input_entries.get(key)
            if (
                matched_entry is None
                or StatisticalObservationReference.from_entry(matched_entry) != item.reference
            ):
                raise ValueError("excluded entry reference does not match an analysis input")
        if set(included_ids) & set(excluded_ids):
            raise ValueError("an entry cannot be both included and excluded")
        if set(included_ids) | set(excluded_ids) != set(input_entries):
            raise ValueError(
                "support must explicitly account for every analysis-input entry; "
                "hidden filtering is forbidden"
            )
        reference_set = set(self.reference_entry_ids)
        if len(reference_set) != len(self.reference_entry_ids):
            raise ValueError("reference_entry_ids must be unique")
        if self.current_entry_id is not None:
            if self.current_entry_id not in {
                entry.canonical_entry_id for entry in self.included_entries
            }:
                raise ValueError("current_entry_id must identify an included entry")
            if self.current_entry_id in reference_set:
                raise ValueError("current entry must be excluded from reference entries")
        if any(
            entry_id not in {entry.canonical_entry_id for entry in self.included_entries}
            for entry_id in self.reference_entry_ids
        ):
            raise ValueError("reference entries must be included in support")
        reference_entries = tuple(
            entry for entry in self.included_entries if entry.canonical_entry_id in reference_set
        )
        expected_reference_ids = tuple(entry.canonical_entry_id for entry in reference_entries)
        if self.reference_entry_ids != expected_reference_ids:
            raise ValueError("reference_entry_ids must use canonical temporal ordering")
        source_record_ids = tuple(item.record_id.qualified for item in self.source_records)
        if len(set(source_record_ids)) != len(source_record_ids):
            raise ValueError("source_records must be unique")
        if self.source_records != tuple(
            sorted(self.source_records, key=lambda item: item.record_id.qualified)
        ):
            raise ValueError("source_records must use canonical record ordering")
        if self.window.kind is StatisticalSupportWindowKind.COUNT_WINDOW:
            assert self.window.count is not None
            if self.window.count != len(self.included_entries):
                raise ValueError("COUNT_WINDOW count must equal the selected entry count")
        if self.window.kind is StatisticalSupportWindowKind.TIME_WINDOW:
            assert self.window.start is not None and self.window.end is not None
            for entry in self.included_entries:
                at = entry.observed_at
                left = (
                    at >= self.window.start
                    if self.window.start_inclusive
                    else at > self.window.start
                )
                right = at <= self.window.end if self.window.end_inclusive else at < self.window.end
                if not left or not right:
                    raise ValueError("included entry falls outside its TIME_WINDOW bounds")
        if self.analysis_inputs and any(
            analysis_input.athlete.athlete_id.qualified not in input_athletes.values()
            for analysis_input in self.analysis_inputs
        ):
            raise ValueError("analysis input athlete identity is not represented")

        expected_hash = _statistical_support_hash(self)
        expected_id = InstanceIdentifier(
            "statistical-support",
            expected_hash.removeprefix(_SHA256_PREFIX),
        )
        if self.support_hash is None:
            object.__setattr__(self, "support_hash", expected_hash)
        elif self.support_hash != expected_hash:
            raise ValueError("support_hash does not match exact support content")
        if self.support_id is None:
            object.__setattr__(self, "support_id", expected_id)
        elif self.support_id != expected_id:
            raise ValueError("support_id does not match exact support content")

    @property
    def input_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.input_id for item in self.analysis_inputs)

    @property
    def input_hashes(self) -> tuple[str, ...]:
        return tuple(item.input_hash for item in self.analysis_inputs)

    @property
    def input_id(self) -> InstanceIdentifier:
        if len(self.analysis_inputs) != 1:
            raise ValueError("support contains multiple analysis inputs")
        return self.analysis_inputs[0].input_id

    @property
    def analysis_input(self) -> MultiSourceAnalysisInput:
        if len(self.analysis_inputs) != 1:
            raise ValueError("support contains multiple analysis inputs")
        return self.analysis_inputs[0]

    @property
    def canonical_support_id(self) -> InstanceIdentifier:
        assert self.support_id is not None
        return self.support_id

    @property
    def canonical_support_hash(self) -> str:
        assert self.support_hash is not None
        return self.support_hash

    @property
    def source_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(entry.source_observation_id for entry in self.included_entries)

    @property
    def source_entry_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(entry.canonical_entry_id for entry in self.included_entries)

    @property
    def source_entry_hashes(self) -> tuple[str, ...]:
        return tuple(entry.canonical_entry_hash for entry in self.included_entries)

    @property
    def source_observation_hashes(self) -> tuple[str, ...]:
        return tuple(canonical_hash(entry.observation) for entry in self.included_entries)

    @property
    def entries(self) -> tuple[LongitudinalObservationEntry, ...]:
        return self.included_entries

    @property
    def selected_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return self.source_observation_ids

    @property
    def source_record_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.record_id for item in self.source_records)

    @property
    def source_record_hashes(self) -> tuple[str, ...]:
        return tuple(item.record_hash for item in self.source_records)

    @property
    def excluded_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.reference.observation_id for item in self.excluded_entries)

    @property
    def excluded_entry_hashes(self) -> tuple[str, ...]:
        return tuple(item.reference.entry_hash for item in self.excluded_entries)

    @property
    def athlete_ids(self) -> tuple[InstanceIdentifier, ...]:
        seen: dict[str, InstanceIdentifier] = {}
        for entry in self.included_entries:
            seen.setdefault(
                entry.observation.context.athlete_id.qualified, entry.observation.context.athlete_id
            )
        return tuple(seen.values())

    @property
    def source_artifacts(self) -> tuple[StatisticalSourceArtifactReference, ...]:
        by_id: dict[str, StatisticalSourceArtifactReference] = {}
        for entry in (*self.included_entries, *(item for item in self._excluded_entry_objects())):
            for artifact in entry.observation.provenance.source_artifacts:
                reference = StatisticalSourceArtifactReference(
                    artifact.artifact_id,
                    artifact.content_digest,
                )
                previous = by_id.get(reference.artifact_id.qualified)
                if previous is not None and previous != reference:
                    raise ValueError("source artifact identity is conflicting in support")
                by_id[reference.artifact_id.qualified] = reference
        return tuple(by_id[key] for key in sorted(by_id))

    @property
    def source_provenance(self) -> tuple[StatisticalProvenanceReference, ...]:
        by_id: dict[str, StatisticalProvenanceReference] = {}
        for entry in (*self.included_entries, *(item for item in self._excluded_entry_objects())):
            provenance = entry.observation.provenance
            reference = StatisticalProvenanceReference(
                provenance.provenance_id,
                canonical_hash(provenance),
            )
            by_id[reference.provenance_id.qualified] = reference
        return tuple(by_id[key] for key in sorted(by_id))

    def _excluded_entry_objects(self) -> tuple[LongitudinalObservationEntry, ...]:
        by_id = {
            entry.canonical_entry_id.qualified: entry
            for analysis_input in self.analysis_inputs
            for entry in analysis_input.entries
        }
        return tuple(by_id[item.reference.entry_id.qualified] for item in self.excluded_entries)


def _statistical_support_hash(support: StatisticalSupport) -> str:
    return canonical_hash(
        {
            "analysis_inputs": support.analysis_inputs,
            "included_entries": support.included_entries,
            "excluded_entries": support.excluded_entries,
            "missingness_policy": support.missingness_policy,
            "window": support.window,
            "source_records": support.source_records,
            "comparability_evidence": support.comparability_evidence,
            "current_entry_id": support.current_entry_id,
            "reference_entry_ids": support.reference_entry_ids,
        }
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReliabilityReplicatePair:
    pair_id: InstanceIdentifier
    athlete_id: InstanceIdentifier
    occasion_id: InstanceIdentifier
    first: StatisticalObservationReference
    second: StatisticalObservationReference

    def __post_init__(self) -> None:
        _require_identifier(self.pair_id, "reliability-pair", "pair_id")
        _require_identifier(self.athlete_id, "athlete", "athlete_id")
        _require_identifier(self.occasion_id, "occasion", "occasion_id")
        _require_instance(self.first, StatisticalObservationReference, "first")
        _require_instance(self.second, StatisticalObservationReference, "second")
        if self.first.athlete_id != self.athlete_id or self.second.athlete_id != self.athlete_id:
            raise ValueError("replicate pair athlete identity must match both observations")
        if self.first.observation_id == self.second.observation_id:
            raise ValueError("replicate pair requires two distinct observations")
        expected_id = InstanceIdentifier(
            "reliability-pair",
            canonical_hash(
                {
                    "athlete_id": self.athlete_id,
                    "occasion_id": self.occasion_id,
                    "first": self.first,
                    "second": self.second,
                }
            ).removeprefix(_SHA256_PREFIX),
        )
        if self.pair_id != expected_id:
            raise ValueError("pair_id does not match immutable replicate ordering and content")

    @classmethod
    def from_entries(
        cls,
        first: LongitudinalObservationEntry,
        second: LongitudinalObservationEntry,
        *,
        occasion_id: InstanceIdentifier | None = None,
    ) -> ReliabilityReplicatePair:
        first_ref = StatisticalObservationReference.from_entry(first)
        second_ref = StatisticalObservationReference.from_entry(second)
        if first_ref.athlete_id != second_ref.athlete_id:
            raise ValueError("replicate pair entries must belong to one athlete")
        occasion = occasion_id or InstanceIdentifier("occasion", first_ref.session_id.value)
        _require_identifier(occasion, "occasion", "occasion_id")
        pair_id = InstanceIdentifier(
            "reliability-pair",
            canonical_hash(
                {
                    "athlete_id": first_ref.athlete_id,
                    "occasion_id": occasion,
                    "first": first_ref,
                    "second": second_ref,
                }
            ).removeprefix(_SHA256_PREFIX),
        )
        return cls(pair_id, first_ref.athlete_id, occasion, first_ref, second_ref)

    @property
    def first_entry_id(self) -> InstanceIdentifier:
        return self.first.entry_id

    @property
    def second_entry_id(self) -> InstanceIdentifier:
        return self.second.entry_id

    @property
    def first_observation_id(self) -> InstanceIdentifier:
        return self.first.observation_id

    @property
    def second_observation_id(self) -> InstanceIdentifier:
        return self.second.observation_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MethodComparisonPair:
    pair_id: InstanceIdentifier
    athlete_id: InstanceIdentifier
    occasion_id: InstanceIdentifier
    method_a: StatisticalObservationReference
    method_b: StatisticalObservationReference

    def __post_init__(self) -> None:
        _require_identifier(self.pair_id, "method-comparison-pair", "pair_id")
        _require_identifier(self.athlete_id, "athlete", "athlete_id")
        _require_identifier(self.occasion_id, "occasion", "occasion_id")
        _require_instance(self.method_a, StatisticalObservationReference, "method_a")
        _require_instance(self.method_b, StatisticalObservationReference, "method_b")
        if (
            self.method_a.athlete_id != self.athlete_id
            or self.method_b.athlete_id != self.athlete_id
        ):
            raise ValueError("method comparison pair athlete identity must match both observations")
        if self.method_a.observation_id == self.method_b.observation_id:
            raise ValueError("method comparison pair requires two distinct observations")
        expected_id = InstanceIdentifier(
            "method-comparison-pair",
            canonical_hash(
                {
                    "athlete_id": self.athlete_id,
                    "occasion_id": self.occasion_id,
                    "method_a": self.method_a,
                    "method_b": self.method_b,
                }
            ).removeprefix(_SHA256_PREFIX),
        )
        if self.pair_id != expected_id:
            raise ValueError("pair_id does not match immutable method pairing and content")

    @classmethod
    def from_entries(
        cls,
        method_a: LongitudinalObservationEntry,
        method_b: LongitudinalObservationEntry,
        *,
        occasion_id: InstanceIdentifier | None = None,
    ) -> MethodComparisonPair:
        first = StatisticalObservationReference.from_entry(method_a)
        second = StatisticalObservationReference.from_entry(method_b)
        if first.athlete_id != second.athlete_id:
            raise ValueError("method comparison entries must belong to one athlete")
        occasion = occasion_id or InstanceIdentifier("occasion", first.session_id.value)
        _require_identifier(occasion, "occasion", "occasion_id")
        pair_id = InstanceIdentifier(
            "method-comparison-pair",
            canonical_hash(
                {
                    "athlete_id": first.athlete_id,
                    "occasion_id": occasion,
                    "method_a": first,
                    "method_b": second,
                }
            ).removeprefix(_SHA256_PREFIX),
        )
        return cls(pair_id, first.athlete_id, occasion, first, second)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SystematicTrialEffectAssessment:
    status: SystematicTrialEffectStatus
    evidence_references: tuple[EvidenceReference, ...]
    description: str

    def __post_init__(self) -> None:
        _require_enum(self.status, SystematicTrialEffectStatus, "status")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        _require_text(self.description, "description")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReliabilityDesignEvidence:
    """Source/protocol evidence from which reliability authority is normalized."""

    support: StatisticalSupport
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...]
    study_identity: RegistryReference
    replicate_pairs: tuple[ReliabilityReplicatePair, ...]
    replicate_ordering: RegistryReference
    target_measurement_identity_ids: tuple[ScientificIdentifier, ...]
    target_construct: RegistryReference
    target_test_family: RegistryReference
    target_measurand: RegistryReference
    target_metric_definition: RegistryReference
    target_unit: UnitReference
    protocol_reference: RegistryReference
    method_identity: RegistryReference | None
    device_identity: RegistryReference | None
    rater_identity: RegistryReference | None
    evidence_references: tuple[EvidenceReference, ...]
    repeatability_question: ReliabilityQuestion
    stable_underlying_quantity: StableUnderlyingQuantityStatus
    systematic_trial_effect: SystematicTrialEffectAssessment
    error_scale: ReliabilityErrorScale
    missingness_policy: MissingnessPolicy
    balanced_design: bool
    producing_method: RegistryReference
    registry_version: str
    design_identity: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_instance(self.support, StatisticalSupport, "support")
        _require_tuple_items(
            self.source_records, LongitudinalAthletePerformanceRecord, "source_records"
        )
        if not self.source_records:
            raise ValueError("reliability design evidence requires source records")
        _require_instance(self.study_identity, RegistryReference, "study_identity")
        require_tuple(self.replicate_pairs, "replicate_pairs")
        if any(not isinstance(item, ReliabilityReplicatePair) for item in self.replicate_pairs):
            raise ValueError("replicate_pairs must contain ReliabilityReplicatePair values")
        if not self.replicate_pairs:
            raise ValueError("reliability design evidence requires replicate pairs")
        _require_instance(self.replicate_ordering, RegistryReference, "replicate_ordering")
        require_tuple(self.target_measurement_identity_ids, "target_measurement_identity_ids")
        object.__setattr__(
            self,
            "target_measurement_identity_ids",
            tuple(
                _require_scientific_identifier(item, "target_measurement_identity_ids item")
                for item in self.target_measurement_identity_ids
            ),
        )
        if not self.target_measurement_identity_ids:
            raise ValueError("target measurement identity IDs must not be empty")
        for field_name in (
            "target_construct",
            "target_test_family",
            "target_measurand",
            "target_metric_definition",
            "protocol_reference",
            "producing_method",
        ):
            _require_instance(getattr(self, field_name), RegistryReference, field_name)
        _require_instance(self.target_unit, UnitReference, "target_unit")
        _require_optional_instance(self.method_identity, RegistryReference, "method_identity")
        _require_optional_instance(self.device_identity, RegistryReference, "device_identity")
        _require_optional_instance(self.rater_identity, RegistryReference, "rater_identity")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        if not self.evidence_references:
            raise ValueError("reliability design evidence requires evidence references")
        _require_enum(self.repeatability_question, ReliabilityQuestion, "repeatability_question")
        _require_enum(
            self.stable_underlying_quantity,
            StableUnderlyingQuantityStatus,
            "stable_underlying_quantity",
        )
        _require_instance(
            self.systematic_trial_effect,
            SystematicTrialEffectAssessment,
            "systematic_trial_effect",
        )
        _require_enum(self.error_scale, ReliabilityErrorScale, "error_scale")
        _require_enum(self.missingness_policy, MissingnessPolicy, "missingness_policy")
        _require_bool(self.balanced_design, "balanced_design")
        _require_text(self.registry_version, "registry_version")
        _require_optional_instance(self.design_identity, RegistryReference, "design_identity")


def _authority_payload(value: object) -> dict[str, object]:
    excluded = {"authority_hash", "authority_token", "authority_status"}
    if not hasattr(value, "__dataclass_fields__"):
        raise ValueError("authority payload requires a dataclass")
    return {
        field.name: getattr(value, field.name)
        for field in fields(cast(Any, value))
        if field.name not in excluded
    }


def _authority_hash(value: object) -> str:
    return canonical_hash(_authority_payload(value))


def _authority_token(value: str) -> str:
    return canonical_hash({"authority_hash": value, "purpose": "RES69_SOURCE_BOUND_AUTHORITY_V1"})


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReliabilityDesignAuthority:
    """Normalized reliability authority; direct construction is unverified."""

    support_id: InstanceIdentifier
    support_hash: str
    analysis_input_ids: tuple[InstanceIdentifier, ...]
    analysis_input_hashes: tuple[str, ...]
    source_records: tuple[StatisticalSourceRecordReference, ...]
    source_artifacts: tuple[StatisticalSourceArtifactReference, ...]
    source_provenance: tuple[StatisticalProvenanceReference, ...]
    study_identity: RegistryReference
    replicate_pairs: tuple[ReliabilityReplicatePair, ...]
    replicate_ordering: RegistryReference
    target_measurement_identity_ids: tuple[ScientificIdentifier, ...]
    target_construct: RegistryReference
    target_test_family: RegistryReference
    target_measurand: RegistryReference
    target_metric_definition: RegistryReference
    target_unit: UnitReference
    protocol_reference: RegistryReference
    method_identity: RegistryReference | None
    device_identity: RegistryReference | None
    rater_identity: RegistryReference | None
    evidence_references: tuple[EvidenceReference, ...]
    repeatability_question: ReliabilityQuestion
    stable_underlying_quantity: StableUnderlyingQuantityStatus
    systematic_trial_effect: SystematicTrialEffectAssessment
    error_scale: ReliabilityErrorScale
    missingness_policy: MissingnessPolicy
    balanced_design: bool
    producing_method: RegistryReference
    registry_version: str
    source_evidence_hash: str
    authority_status: AuthorityStatus = AuthorityStatus.UNVERIFIED
    authority_hash: str | None = None
    authority_token: str | None = None
    design_identity: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.support_id, "statistical-support", "support_id")
        _require_hash(self.support_hash, "support_hash")
        require_tuple(self.analysis_input_ids, "analysis_input_ids")
        require_tuple(self.analysis_input_hashes, "analysis_input_hashes")
        if len(self.analysis_input_ids) != len(self.analysis_input_hashes):
            raise ValueError("analysis input IDs and hashes must have equal length")
        for item in self.analysis_input_ids:
            _require_identifier(item, "multi-source-analysis-input", "analysis_input_ids item")
        for input_hash in self.analysis_input_hashes:
            _require_hash(input_hash, "analysis_input_hashes item")
        _require_tuple_items(
            self.source_records, StatisticalSourceRecordReference, "source_records"
        )
        _require_tuple_items(
            self.source_artifacts, StatisticalSourceArtifactReference, "source_artifacts"
        )
        _require_tuple_items(
            self.source_provenance, StatisticalProvenanceReference, "source_provenance"
        )
        _require_instance(self.study_identity, RegistryReference, "study_identity")
        _require_tuple_items(self.replicate_pairs, ReliabilityReplicatePair, "replicate_pairs")
        _require_instance(self.replicate_ordering, RegistryReference, "replicate_ordering")
        object.__setattr__(
            self,
            "target_measurement_identity_ids",
            tuple(
                _require_scientific_identifier(item, "target_measurement_identity_ids item")
                for item in self.target_measurement_identity_ids
            ),
        )
        for field_name in (
            "target_construct",
            "target_test_family",
            "target_measurand",
            "target_metric_definition",
            "protocol_reference",
            "producing_method",
        ):
            _require_instance(getattr(self, field_name), RegistryReference, field_name)
        _require_instance(self.target_unit, UnitReference, "target_unit")
        _require_optional_instance(self.method_identity, RegistryReference, "method_identity")
        _require_optional_instance(self.device_identity, RegistryReference, "device_identity")
        _require_optional_instance(self.rater_identity, RegistryReference, "rater_identity")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        _require_enum(self.repeatability_question, ReliabilityQuestion, "repeatability_question")
        _require_enum(
            self.stable_underlying_quantity,
            StableUnderlyingQuantityStatus,
            "stable_underlying_quantity",
        )
        _require_instance(
            self.systematic_trial_effect,
            SystematicTrialEffectAssessment,
            "systematic_trial_effect",
        )
        _require_enum(self.error_scale, ReliabilityErrorScale, "error_scale")
        _require_enum(self.missingness_policy, MissingnessPolicy, "missingness_policy")
        _require_bool(self.balanced_design, "balanced_design")
        _require_text(self.registry_version, "registry_version")
        _require_hash(self.source_evidence_hash, "source_evidence_hash")
        _require_enum(self.authority_status, AuthorityStatus, "authority_status")
        _require_optional_instance(self.design_identity, RegistryReference, "design_identity")
        expected_hash = _authority_hash(self)
        if self.authority_hash is None:
            object.__setattr__(self, "authority_hash", expected_hash)
        elif self.authority_hash != expected_hash:
            raise ValueError("reliability authority hash does not match immutable content")
        if self.authority_status is AuthorityStatus.SOURCE_BOUND:
            expected_token = _authority_token(expected_hash)
            if self.authority_token != expected_token:
                raise ValueError("source-bound reliability authority proof is invalid")
        elif self.authority_token is not None:
            raise ValueError("unverified reliability authority must not carry an authority token")

    @property
    def is_source_bound(self) -> bool:
        return (
            self.authority_status is AuthorityStatus.SOURCE_BOUND
            and self.authority_token == _authority_token(self.canonical_authority_hash)
        )

    @property
    def canonical_authority_hash(self) -> str:
        assert self.authority_hash is not None
        return self.authority_hash

    @property
    def design_or_study_identity(self) -> RegistryReference:
        return self.design_identity or self.study_identity

    @property
    def athlete_ids(self) -> tuple[InstanceIdentifier, ...]:
        seen: dict[str, InstanceIdentifier] = {}
        for pair in self.replicate_pairs:
            seen.setdefault(pair.athlete_id.qualified, pair.athlete_id)
        return tuple(seen.values())


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MethodComparisonDesignEvidence:
    """Source/protocol evidence from which method-comparison authority is built."""

    support: StatisticalSupport
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...]
    design_identity: RegistryReference
    pairs: tuple[MethodComparisonPair, ...]
    method_a_identity: ScientificIdentifier
    method_b_identity: ScientificIdentifier
    target_construct: RegistryReference
    target_measurand: RegistryReference
    metric_a_definition: RegistryReference
    metric_b_definition: RegistryReference
    unit_a: UnitReference
    unit_b: UnitReference
    occasion_context_policy: RegistryReference
    sign_convention: RegistryReference
    hidden_transformation: bool
    repeated_pair_policy: RepeatedPairPolicy
    evidence_references: tuple[EvidenceReference, ...]
    producing_method: RegistryReference
    registry_version: str

    def __post_init__(self) -> None:
        _require_instance(self.support, StatisticalSupport, "support")
        _require_tuple_items(
            self.source_records, LongitudinalAthletePerformanceRecord, "source_records"
        )
        if not self.source_records:
            raise ValueError("method comparison evidence requires source records")
        _require_instance(self.design_identity, RegistryReference, "design_identity")
        _require_tuple_items(self.pairs, MethodComparisonPair, "pairs")
        if not self.pairs:
            raise ValueError("method comparison evidence requires exact subject pairs")
        object.__setattr__(
            self,
            "method_a_identity",
            _require_scientific_identifier(self.method_a_identity, "method_a_identity"),
        )
        object.__setattr__(
            self,
            "method_b_identity",
            _require_scientific_identifier(self.method_b_identity, "method_b_identity"),
        )
        for field_name in (
            "target_construct",
            "target_measurand",
            "metric_a_definition",
            "metric_b_definition",
            "occasion_context_policy",
            "sign_convention",
            "producing_method",
        ):
            _require_instance(getattr(self, field_name), RegistryReference, field_name)
        _require_instance(self.unit_a, UnitReference, "unit_a")
        _require_instance(self.unit_b, UnitReference, "unit_b")
        _require_bool(self.hidden_transformation, "hidden_transformation")
        _require_enum(self.repeated_pair_policy, RepeatedPairPolicy, "repeated_pair_policy")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        if not self.evidence_references:
            raise ValueError("method comparison evidence requires evidence references")
        _require_text(self.registry_version, "registry_version")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MethodComparisonDesignAuthority:
    """Normalized method-comparison authority; direct construction is unverified."""

    support_id: InstanceIdentifier
    support_hash: str
    analysis_input_ids: tuple[InstanceIdentifier, ...]
    analysis_input_hashes: tuple[str, ...]
    source_records: tuple[StatisticalSourceRecordReference, ...]
    source_artifacts: tuple[StatisticalSourceArtifactReference, ...]
    source_provenance: tuple[StatisticalProvenanceReference, ...]
    design_identity: RegistryReference
    pairs: tuple[MethodComparisonPair, ...]
    method_a_identity: ScientificIdentifier
    method_b_identity: ScientificIdentifier
    target_construct: RegistryReference
    target_measurand: RegistryReference
    metric_a_definition: RegistryReference
    metric_b_definition: RegistryReference
    unit_a: UnitReference
    unit_b: UnitReference
    occasion_context_policy: RegistryReference
    sign_convention: RegistryReference
    hidden_transformation: bool
    repeated_pair_policy: RepeatedPairPolicy
    evidence_references: tuple[EvidenceReference, ...]
    producing_method: RegistryReference
    registry_version: str
    source_evidence_hash: str
    authority_status: AuthorityStatus = AuthorityStatus.UNVERIFIED
    authority_hash: str | None = None
    authority_token: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.support_id, "statistical-support", "support_id")
        _require_hash(self.support_hash, "support_hash")
        require_tuple(self.analysis_input_ids, "analysis_input_ids")
        require_tuple(self.analysis_input_hashes, "analysis_input_hashes")
        if len(self.analysis_input_ids) != len(self.analysis_input_hashes):
            raise ValueError("analysis input IDs and hashes must have equal length")
        for item in self.analysis_input_ids:
            _require_identifier(item, "multi-source-analysis-input", "analysis_input_ids item")
        for input_hash in self.analysis_input_hashes:
            _require_hash(input_hash, "analysis_input_hashes item")
        _require_tuple_items(
            self.source_records, StatisticalSourceRecordReference, "source_records"
        )
        _require_tuple_items(
            self.source_artifacts, StatisticalSourceArtifactReference, "source_artifacts"
        )
        _require_tuple_items(
            self.source_provenance, StatisticalProvenanceReference, "source_provenance"
        )
        _require_instance(self.design_identity, RegistryReference, "design_identity")
        _require_tuple_items(self.pairs, MethodComparisonPair, "pairs")
        object.__setattr__(
            self,
            "method_a_identity",
            _require_scientific_identifier(self.method_a_identity, "method_a_identity"),
        )
        object.__setattr__(
            self,
            "method_b_identity",
            _require_scientific_identifier(self.method_b_identity, "method_b_identity"),
        )
        for field_name in (
            "target_construct",
            "target_measurand",
            "metric_a_definition",
            "metric_b_definition",
            "occasion_context_policy",
            "sign_convention",
            "producing_method",
        ):
            _require_instance(getattr(self, field_name), RegistryReference, field_name)
        _require_instance(self.unit_a, UnitReference, "unit_a")
        _require_instance(self.unit_b, UnitReference, "unit_b")
        _require_bool(self.hidden_transformation, "hidden_transformation")
        _require_enum(self.repeated_pair_policy, RepeatedPairPolicy, "repeated_pair_policy")
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        _require_text(self.registry_version, "registry_version")
        _require_hash(self.source_evidence_hash, "source_evidence_hash")
        _require_enum(self.authority_status, AuthorityStatus, "authority_status")
        expected_hash = _authority_hash(self)
        if self.authority_hash is None:
            object.__setattr__(self, "authority_hash", expected_hash)
        elif self.authority_hash != expected_hash:
            raise ValueError("method-comparison authority hash does not match immutable content")
        if self.authority_status is AuthorityStatus.SOURCE_BOUND:
            if self.authority_token != _authority_token(expected_hash):
                raise ValueError("source-bound method-comparison authority proof is invalid")
        elif self.authority_token is not None:
            raise ValueError(
                "unverified method-comparison authority must not carry an authority token"
            )

    @property
    def is_source_bound(self) -> bool:
        return (
            self.authority_status is AuthorityStatus.SOURCE_BOUND
            and self.authority_token == _authority_token(self.canonical_authority_hash)
        )

    @property
    def canonical_authority_hash(self) -> str:
        assert self.authority_hash is not None
        return self.authority_hash


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalNonComputable:
    operation: RegistryReference
    disposition: StatisticalOperationDisposition
    reason: str

    def __post_init__(self) -> None:
        _require_instance(self.operation, RegistryReference, "operation")
        if self.operation.identifier.object_type != "registered-operation":
            raise ValueError("operation must identify a registered operation")
        _require_enum(self.disposition, StatisticalOperationDisposition, "disposition")
        _require_text(self.reason, "reason")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalEstimate:
    estimate_id: InstanceIdentifier
    estimand: RegistryReference
    value: float
    unit: StatisticalUnitReference
    estimator: RegistryReference
    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.estimate_id, "statistical-estimate", "estimate_id")
        _require_instance(self.estimand, RegistryReference, "estimand")
        if self.estimand.identifier.object_type != "estimand":
            raise ValueError("estimand must identify a registered estimand")
        value = _require_finite_number(self.value, "value")
        object.__setattr__(self, "value", value)
        if not isinstance(self.unit, UnitReference | DerivedUnitReference):
            raise ValueError("unit must be a UnitReference or DerivedUnitReference")
        _require_instance(self.estimator, RegistryReference, "estimator")
        if self.estimator.identifier.object_type != "estimator":
            raise ValueError("estimator must identify a registered estimator")
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")

    @property
    def unit_reference(self) -> StatisticalUnitReference:
        return self.unit


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalAnalysisRun:
    analysis_inputs: tuple[MultiSourceAnalysisInput, ...]
    support_id: InstanceIdentifier
    support_hash: str
    operation: RegistryReference
    estimator: RegistryReference
    parameters: tuple[MetadataEntry, ...]
    software_version: str
    registry_version: str
    processing_runs: tuple[MultiSourceProcessingRun, ...]
    provenance_graphs: tuple[MultiSourceProvenanceGraph, ...]
    source_records: tuple[StatisticalSourceRecordReference, ...]
    evidence_references: tuple[EvidenceReference, ...]
    analysis_run_id: InstanceIdentifier | None = None
    support: StatisticalSupport | None = None
    scale_semantic_key: MeasurementScaleSemanticKeyV1 | None = None
    scale_semantics_authority: RegistryReference | None = None
    scale_semantics_hash: str | None = None
    authority_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.analysis_inputs, "analysis_inputs")
        if not self.analysis_inputs:
            raise ValueError("analysis run requires analysis inputs")
        if any(not isinstance(item, MultiSourceAnalysisInput) for item in self.analysis_inputs):
            raise ValueError("analysis_inputs must contain MultiSourceAnalysisInput values")
        _require_identifier(self.support_id, "statistical-support", "support_id")
        _require_hash(self.support_hash, "support_hash")
        _require_instance(self.operation, RegistryReference, "operation")
        if self.operation.identifier.object_type != "registered-operation":
            raise ValueError("operation must identify a registered operation")
        _require_instance(self.estimator, RegistryReference, "estimator")
        if self.estimator.identifier.object_type != "estimator":
            raise ValueError("estimator must identify a registered estimator")
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")
        _require_text(self.software_version, "software_version")
        _require_text(self.registry_version, "registry_version")
        require_tuple(self.processing_runs, "processing_runs")
        require_tuple(self.provenance_graphs, "provenance_graphs")
        if len(self.processing_runs) != len(self.analysis_inputs):
            raise ValueError("one RES-62 processing run is required per analysis input")
        if len(self.provenance_graphs) != len(self.analysis_inputs):
            raise ValueError("one RES-62 provenance graph is required per analysis input")
        _require_tuple_items(self.processing_runs, MultiSourceProcessingRun, "processing_runs")
        _require_tuple_items(
            self.provenance_graphs, MultiSourceProvenanceGraph, "provenance_graphs"
        )
        _require_tuple_items(
            self.source_records, StatisticalSourceRecordReference, "source_records"
        )
        _require_tuple_items(self.evidence_references, EvidenceReference, "evidence_references")
        _require_optional_instance(self.support, StatisticalSupport, "support")
        if self.support is not None:
            if self.support.analysis_inputs != self.analysis_inputs:
                raise ValueError("analysis run support inputs must match analysis_inputs")
            if self.support.source_records != self.source_records:
                raise ValueError("analysis run support records must match source_records")
            if self.support.canonical_support_id != self.support_id:
                raise ValueError("analysis run support ID must match support_id")
            if self.support.canonical_support_hash != self.support_hash:
                raise ValueError("analysis run support hash must match support_hash")
        _require_optional_instance(
            self.scale_semantic_key,
            MeasurementScaleSemanticKeyV1,
            "scale_semantic_key",
        )
        _require_optional_instance(
            self.scale_semantics_authority,
            RegistryReference,
            "scale_semantics_authority",
        )
        if self.scale_semantics_hash is not None:
            _require_hash(self.scale_semantics_hash, "scale_semantics_hash")
            if self.scale_semantics_authority is None or self.scale_semantic_key is None:
                raise ValueError(
                    "scale semantics hash requires its semantic key and authority reference"
                )
        if self.scale_semantics_authority is not None and self.scale_semantic_key is None:
            raise ValueError("scale semantics authority requires its semantic key")
        if self.scale_semantics_authority is not None and self.scale_semantics_hash is None:
            raise ValueError("scale semantics authority requires its canonical authority hash")
        require_tuple(self.authority_hashes, "authority_hashes")
        for authority_hash in self.authority_hashes:
            _require_hash(authority_hash, "authority_hashes item")
        for analysis_input, processing_run, graph in zip(
            self.analysis_inputs,
            self.processing_runs,
            self.provenance_graphs,
            strict=True,
        ):
            if processing_run.method != self.operation:
                raise ValueError("processing run method must equal the statistical operation")
            if processing_run.analysis_input_id != analysis_input.input_id:
                raise ValueError("processing run must reference its analysis input")
            if processing_run.analysis_input_hash != analysis_input.input_hash:
                raise ValueError("processing run input hash must match its analysis input")
            from dynamislm.longitudinal.lineage import validate_multi_source_provenance_graph

            validate_multi_source_provenance_graph(graph, analysis_input, processing_run)
        expected_hash = _analysis_run_hash(self)
        expected_id = InstanceIdentifier(
            "statistical-analysis-run",
            expected_hash.removeprefix(_SHA256_PREFIX),
        )
        if self.analysis_run_id is None:
            object.__setattr__(self, "analysis_run_id", expected_id)
        elif self.analysis_run_id != expected_id:
            raise ValueError("analysis_run_id does not match immutable analysis-run content")

    @property
    def run_id(self) -> InstanceIdentifier:
        assert self.analysis_run_id is not None
        return self.analysis_run_id

    @property
    def analysis_run_hash(self) -> str:
        return _analysis_run_hash(self)

    @property
    def source_observation_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(
            observation_id
            for analysis_input in self.analysis_inputs
            for observation_id in analysis_input.source_observation_ids
        )

    @property
    def source_entry_hashes(self) -> tuple[str, ...]:
        return tuple(
            entry_hash
            for analysis_input in self.analysis_inputs
            for entry_hash in analysis_input.selected_entry_hashes
        )

    @property
    def support_snapshot(self) -> StatisticalSupport | None:
        return self.support

    @property
    def source_record_ids(self) -> tuple[InstanceIdentifier, ...]:
        return tuple(item.record_id for item in self.source_records)

    @property
    def source_record_hashes(self) -> tuple[str, ...]:
        return tuple(item.record_hash for item in self.source_records)

    @property
    def processing_run(self) -> MultiSourceProcessingRun:
        if len(self.processing_runs) != 1:
            raise ValueError("analysis run contains multiple RES-62 processing runs")
        return self.processing_runs[0]

    @property
    def provenance_graph(self) -> MultiSourceProvenanceGraph:
        if len(self.provenance_graphs) != 1:
            raise ValueError("analysis run contains multiple provenance graphs")
        return self.provenance_graphs[0]


def _analysis_run_hash(run: StatisticalAnalysisRun) -> str:
    return canonical_hash(
        {
            "analysis_inputs": run.analysis_inputs,
            "support_id": run.support_id,
            "support_hash": run.support_hash,
            "operation": run.operation,
            "estimator": run.estimator,
            "parameters": run.parameters,
            "software_version": run.software_version,
            "registry_version": run.registry_version,
            "processing_runs": run.processing_runs,
            "provenance_graphs": run.provenance_graphs,
            "source_records": run.source_records,
            "evidence_references": run.evidence_references,
            "support": run.support,
            "scale_semantic_key": run.scale_semantic_key,
            "scale_semantics_authority": run.scale_semantics_authority,
            "scale_semantics_hash": run.scale_semantics_hash,
            "authority_hashes": run.authority_hashes,
        }
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalResult:
    analysis_run: StatisticalAnalysisRun
    result_kind: RegistryReference
    estimates: tuple[StatisticalEstimate, ...]
    non_computable: tuple[StatisticalNonComputable, ...] = ()
    authority_references: tuple[RegistryReference, ...] = ()
    result_id: InstanceIdentifier | None = None
    output_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.analysis_run, StatisticalAnalysisRun, "analysis_run")
        _require_instance(self.result_kind, RegistryReference, "result_kind")
        if self.result_kind.identifier.object_type != "registered-operation":
            raise ValueError("result_kind must identify a registered operation")
        _require_tuple_items(self.estimates, StatisticalEstimate, "estimates")
        if not self.estimates:
            raise ValueError("statistical result requires at least one estimate")
        estimate_ids = tuple(item.estimate_id.qualified for item in self.estimates)
        if len(set(estimate_ids)) != len(estimate_ids):
            raise ValueError("statistical estimate IDs must be unique")
        _require_tuple_items(self.non_computable, StatisticalNonComputable, "non_computable")
        _require_tuple_items(self.authority_references, RegistryReference, "authority_references")
        _require_optional_instance(self.result_id, InstanceIdentifier, "result_id")
        if self.result_id is not None and self.result_id.instance_type != "statistical-result":
            raise ValueError("result_id must identify a statistical result")
        if self.output_hash is not None:
            _require_hash(self.output_hash, "output_hash")
        expected_hash = _statistical_result_hash(self)
        expected_id = InstanceIdentifier(
            "statistical-result",
            expected_hash.removeprefix(_SHA256_PREFIX),
        )
        if self.output_hash is None:
            object.__setattr__(self, "output_hash", expected_hash)
        elif self.output_hash != expected_hash:
            raise ValueError("output_hash does not match immutable statistical result")
        if self.result_id is None:
            object.__setattr__(self, "result_id", expected_id)
        elif self.result_id != expected_id:
            raise ValueError("result_id does not match immutable statistical result")

    @property
    def canonical_result_id(self) -> InstanceIdentifier:
        assert self.result_id is not None
        return self.result_id

    @property
    def canonical_output_hash(self) -> str:
        assert self.output_hash is not None
        return self.output_hash

    @property
    def support(self) -> StatisticalSupport | None:
        return self.analysis_run.support

    @property
    def scale_semantic_key(self) -> MeasurementScaleSemanticKeyV1 | None:
        return self.analysis_run.scale_semantic_key

    @property
    def scale_semantics_authority(self) -> RegistryReference | None:
        return self.analysis_run.scale_semantics_authority

    @property
    def scale_semantics_hash(self) -> str | None:
        return self.analysis_run.scale_semantics_hash

    @property
    def authority_hashes(self) -> tuple[str, ...]:
        return self.analysis_run.authority_hashes

    def estimate(self, key: str) -> StatisticalEstimate:
        for estimate in self.estimates:
            if estimate.estimand.identifier.key == key or estimate.estimate_id.value == key:
                return estimate
        raise KeyError(key)

    @property
    def operation(self) -> RegistryReference:
        return self.result_kind

    def get_estimate(self, key: str) -> StatisticalEstimate | None:
        try:
            return self.estimate(key)
        except KeyError:
            return None


def _statistical_result_hash(result: StatisticalResult) -> str:
    return canonical_hash(
        {
            "analysis_run": result.analysis_run,
            "result_kind": result.result_kind,
            "estimates": result.estimates,
            "non_computable": result.non_computable,
            "authority_references": result.authority_references,
        }
    )


__all__ = [
    "AuthorityStatus",
    "DenominatorPolicy",
    "DerivedUnitReference",
    "MeasurementScaleKind",
    "MeasurementScaleSemanticKeyV1",
    "MeasurementScaleSemantics",
    "MethodComparisonDesignAuthority",
    "MethodComparisonDesignEvidence",
    "MethodComparisonPair",
    "MissingnessPolicy",
    "RES69ReasonCode",
    "ReliabilityDesignAuthority",
    "ReliabilityDesignEvidence",
    "ReliabilityErrorScale",
    "ReliabilityQuestion",
    "ReliabilityReplicatePair",
    "RepeatedPairPolicy",
    "ScaleAuthorityOrigin",
    "SignedValuePolicy",
    "StableUnderlyingQuantityStatus",
    "StatisticalAnalysisRun",
    "StatisticalComparabilityEvidence",
    "StatisticalEstimate",
    "StatisticalNonComputable",
    "StatisticalObservationReference",
    "StatisticalOperationDisposition",
    "StatisticalProvenanceReference",
    "StatisticalResult",
    "StatisticalSourceArtifactReference",
    "StatisticalSourceRecordReference",
    "StatisticalSupport",
    "StatisticalSupportWindowKind",
    "StatisticalUnitReference",
    "StatisticalWindow",
    "SupportEntryExclusion",
    "SupportExclusionReason",
    "SupportSelectionStatus",
    "SystematicTrialEffectAssessment",
    "SystematicTrialEffectStatus",
]
