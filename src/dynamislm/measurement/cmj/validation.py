"""Deterministic acquisition-level validation for CMJ raw force signals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.cmj.acquisition import (
    AcquisitionArrangement,
    ArtifactHashScope,
    ArtifactStatus,
    CMJAcquisitionIdentity,
    CMJSourceArtifact,
    CombinationLineageKind,
    ReferenceState,
    SignalProcessingState,
    TimebaseKind,
)
from dynamislm.measurement.cmj.identity import CMJ_TEST_FAMILY, CMJMeasurementIdentity
from dynamislm.measurement.cmj.registry import (
    is_registered_arrangement,
    is_registered_axis,
    is_registered_force_unit,
    is_registered_reference_frame,
)
from dynamislm.measurement.cmj.signal import (
    ExplicitTimebase,
    RawVerticalForceSignal,
    RegularTimebase,
)
from dynamislm.measurement.identity import SignConvention
from dynamislm.provenance.models import SourceArtifact
from dynamislm.serialization import register_serializable_type


class ValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class ValidationIssueKind(StrEnum):
    INVALID = "INVALID"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class CMJValidationCode(StrEnum):
    EMPTY_SIGNAL = "EMPTY_SIGNAL"
    NONFINITE_SAMPLE = "NONFINITE_SAMPLE"
    INVALID_TIMEBASE = "INVALID_TIMEBASE"
    TIME_COUNT_MISMATCH = "TIME_COUNT_MISMATCH"
    NONFINITE_TIME = "NONFINITE_TIME"
    DUPLICATE_TIME = "DUPLICATE_TIME"
    NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
    TIMEBASE_KIND_MISMATCH = "TIMEBASE_KIND_MISMATCH"
    DECLARED_SAMPLE_RATE_MISMATCH = "DECLARED_SAMPLE_RATE_MISMATCH"
    MISSING_PROTOCOL_IDENTITY = "MISSING_PROTOCOL_IDENTITY"
    MISSING_DEVICE_IDENTITY = "MISSING_DEVICE_IDENTITY"
    MISSING_MEASURING_SYSTEM = "MISSING_MEASURING_SYSTEM"
    MISSING_ARRANGEMENT = "MISSING_ARRANGEMENT"
    MISSING_CHANNEL = "MISSING_CHANNEL"
    MISSING_ACQUISITION_INSTANCE = "MISSING_ACQUISITION_INSTANCE"
    ACQUISITION_ID_MISMATCH = "ACQUISITION_ID_MISMATCH"
    CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
    ARRANGEMENT_CHANNEL_INCONSISTENT = "ARRANGEMENT_CHANNEL_INCONSISTENT"
    COMBINATION_LINEAGE_MISSING = "COMBINATION_LINEAGE_MISSING"
    COMBINATION_STATE_MISMATCH = "COMBINATION_STATE_MISMATCH"
    MISSING_AXIS = "MISSING_AXIS"
    UNREGISTERED_AXIS = "UNREGISTERED_AXIS"
    MISSING_REFERENCE_FRAME = "MISSING_REFERENCE_FRAME"
    UNREGISTERED_REFERENCE_FRAME = "UNREGISTERED_REFERENCE_FRAME"
    MISSING_UNIT = "MISSING_UNIT"
    UNREGISTERED_UNIT = "UNREGISTERED_UNIT"
    MISSING_SIGN_CONVENTION = "MISSING_SIGN_CONVENTION"
    SIGNAL_SEMANTICS_MISMATCH = "SIGNAL_SEMANTICS_MISMATCH"
    MISSING_TIMEBASE = "MISSING_TIMEBASE"
    MISSING_ACQUISITION_SOFTWARE = "MISSING_ACQUISITION_SOFTWARE"
    MISSING_ACQUISITION_TIMESTAMP = "MISSING_ACQUISITION_TIMESTAMP"
    PROCESSING_STATE_UNKNOWN = "PROCESSING_STATE_UNKNOWN"
    PROCESSING_STATE_MISMATCH = "PROCESSING_STATE_MISMATCH"
    CALIBRATION_STATE_UNKNOWN = "CALIBRATION_STATE_UNKNOWN"
    ZEROING_STATE_UNKNOWN = "ZEROING_STATE_UNKNOWN"
    SOURCE_ARTIFACT_MISSING = "SOURCE_ARTIFACT_MISSING"
    ARTIFACT_METADATA_INSUFFICIENT = "ARTIFACT_METADATA_INSUFFICIENT"
    ARTIFACT_ID_MISMATCH = "ARTIFACT_ID_MISMATCH"
    ARTIFACT_NOT_IMMUTABLE = "ARTIFACT_NOT_IMMUTABLE"
    ARTIFACT_HASH_INVALID = "ARTIFACT_HASH_INVALID"
    ARTIFACT_HASH_UNVERIFIED = "ARTIFACT_HASH_UNVERIFIED"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    ARTIFACT_ACQUISITION_LINK_MISSING = "ARTIFACT_ACQUISITION_LINK_MISSING"
    ARTIFACT_ACQUISITION_LINK_MISMATCH = "ARTIFACT_ACQUISITION_LINK_MISMATCH"
    ACQUISITION_IDENTITY_MISMATCH = "ACQUISITION_IDENTITY_MISMATCH"
    RAW_ARTIFACT_ID_MISMATCH = "RAW_ARTIFACT_ID_MISMATCH"
    MISSING_ARRANGEMENT_REFERENCE = "MISSING_ARRANGEMENT_REFERENCE"
    UNREGISTERED_ARRANGEMENT_REFERENCE = "UNREGISTERED_ARRANGEMENT_REFERENCE"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJValidationIssue:
    code: CMJValidationCode
    field: str
    kind: ValidationIssueKind
    message: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJValidationResult:
    status: ValidationStatus
    issues: tuple[CMJValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.issues, tuple):
            raise ValueError("validation issues must be an immutable tuple")

    @property
    def is_valid(self) -> bool:
        return self.status is ValidationStatus.VALID

    @property
    def is_insufficient(self) -> bool:
        return self.status is ValidationStatus.INSUFFICIENT_INFORMATION


_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RATE_RELATIVE_TOLERANCE = 1e-9
_RATE_ABSOLUTE_TOLERANCE = 1e-12


def _issue(
    code: CMJValidationCode,
    field: str,
    kind: ValidationIssueKind,
    message: str,
) -> CMJValidationIssue:
    return CMJValidationIssue(code, field, kind, message)


def _same_rate(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=_RATE_RELATIVE_TOLERANCE,
        abs_tol=_RATE_ABSOLUTE_TOLERANCE,
    )


def _timebase_issues(signal: RawVerticalForceSignal) -> list[CMJValidationIssue]:
    if signal.timebase is None:
        return [
            _issue(
                CMJValidationCode.MISSING_TIMEBASE,
                "timebase",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "signal has no regular or explicit timebase",
            )
        ]
    if isinstance(signal.timebase, RegularTimebase):
        return []
    if not isinstance(signal.timebase, ExplicitTimebase):
        return [
            _issue(
                CMJValidationCode.INVALID_TIMEBASE,
                "timebase",
                ValidationIssueKind.INVALID,
                "signal timebase is not a registered timebase type",
            )
        ]
    times = signal.timebase.times_s
    issues: list[CMJValidationIssue] = []
    if len(times) != len(signal.samples):
        issues.append(
            _issue(
                CMJValidationCode.TIME_COUNT_MISMATCH,
                "timebase.times_s",
                ValidationIssueKind.INVALID,
                "explicit time count must equal sample count",
            )
        )
    previous: float | None = None
    for index, time in enumerate(times):
        if isinstance(time, bool) or not isinstance(time, int | float) or not math.isfinite(time):
            issues.append(
                _issue(
                    CMJValidationCode.NONFINITE_TIME,
                    f"timebase.times_s[{index}]",
                    ValidationIssueKind.INVALID,
                    "explicit times must be finite",
                )
            )
            previous = None
            continue
        if previous is not None:
            if time == previous:
                issues.append(
                    _issue(
                        CMJValidationCode.DUPLICATE_TIME,
                        f"timebase.times_s[{index}]",
                        ValidationIssueKind.INVALID,
                        "explicit times must not contain duplicates",
                    )
                )
            elif time < previous:
                issues.append(
                    _issue(
                        CMJValidationCode.NON_MONOTONIC_TIME,
                        f"timebase.times_s[{index}]",
                        ValidationIssueKind.INVALID,
                        "explicit times must be strictly increasing",
                    )
                )
        previous = time
    return issues


def validate_raw_vertical_force_signal(
    signal: RawVerticalForceSignal,
    source_artifact: SourceArtifact | None = None,
) -> CMJValidationResult:
    """Validate signal structure and source-artifact integrity only."""

    issues: list[CMJValidationIssue] = []
    if not signal.samples:
        issues.append(
            _issue(
                CMJValidationCode.EMPTY_SIGNAL,
                "samples",
                ValidationIssueKind.INVALID,
                "raw vertical-force signal must not be empty",
            )
        )
    for index, sample in enumerate(signal.samples):
        if (
            isinstance(sample, bool)
            or not isinstance(sample, int | float)
            or not math.isfinite(sample)
        ):
            issues.append(
                _issue(
                    CMJValidationCode.NONFINITE_SAMPLE,
                    f"samples[{index}]",
                    ValidationIssueKind.INVALID,
                    "raw vertical-force samples must be finite numbers",
                )
            )
    issues.extend(_timebase_issues(signal))
    if signal.processing_state is SignalProcessingState.UNKNOWN:
        issues.append(
            _issue(
                CMJValidationCode.PROCESSING_STATE_UNKNOWN,
                "processing_state",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "signal preprocessing state is unresolved",
            )
        )
    issues.extend(_artifact_issues(signal, source_artifact))
    return _result(issues)


def _artifact_issues(
    signal: RawVerticalForceSignal,
    source_artifact: SourceArtifact | None,
) -> list[CMJValidationIssue]:
    if source_artifact is None:
        return [
            _issue(
                CMJValidationCode.SOURCE_ARTIFACT_MISSING,
                "source_artifact",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "source artifact metadata is required",
            )
        ]
    issues: list[CMJValidationIssue] = []
    if source_artifact.artifact_id != signal.source_artifact_id:
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_ID_MISMATCH,
                "source_artifact.artifact_id",
                ValidationIssueKind.INVALID,
                "source artifact ID does not match signal linkage",
            )
        )
    if not isinstance(source_artifact, CMJSourceArtifact):
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_METADATA_INSUFFICIENT,
                "source_artifact",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "CMJ artifact hash algorithm, scope, and status are unresolved",
            )
        )
        return issues
    if source_artifact.acquisition_id is None:
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_ACQUISITION_LINK_MISSING,
                "source_artifact.acquisition_id",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "source artifact acquisition linkage is missing",
            )
        )
    elif source_artifact.acquisition_id != signal.acquisition_id:
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_ACQUISITION_LINK_MISMATCH,
                "source_artifact.acquisition_id",
                ValidationIssueKind.INVALID,
                "source artifact acquisition linkage does not match signal",
            )
        )
    if not source_artifact.immutable:
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_NOT_IMMUTABLE,
                "source_artifact.immutable",
                ValidationIssueKind.INVALID,
                "raw source artifact must be immutable",
            )
        )
    if source_artifact.hash_algorithm.value != "sha256" or not _SHA256_DIGEST.fullmatch(
        source_artifact.content_digest
    ):
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_HASH_INVALID,
                "source_artifact.content_digest",
                ValidationIssueKind.INVALID,
                "CMJ artifacts require a sha256 digest in canonical form",
            )
        )
    if source_artifact.status is ArtifactStatus.UNVERIFIED:
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_HASH_UNVERIFIED,
                "source_artifact.status",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "source artifact digest has not been verified",
            )
        )
    if (
        source_artifact.status is ArtifactStatus.VERIFIED
        and source_artifact.hash_scope is ArtifactHashScope.CANONICAL_SIGNAL_REPRESENTATION
        and source_artifact.content_digest != signal.canonical_content_digest()
    ):
        issues.append(
            _issue(
                CMJValidationCode.ARTIFACT_HASH_MISMATCH,
                "source_artifact.content_digest",
                ValidationIssueKind.INVALID,
                "source artifact digest does not match canonical signal content",
            )
        )
    return issues


def validate_cmj_acquisition(
    identity: CMJMeasurementIdentity,
    signal: RawVerticalForceSignal,
    source_artifact: SourceArtifact | None = None,
) -> CMJValidationResult:
    """Validate CMJ identity, signal semantics, linkage, and acquisition metadata."""

    issues = list(validate_raw_vertical_force_signal(signal, source_artifact).issues)
    acquisition = identity.acquisition
    if identity.semantic.test_family.identifier.stable_id != CMJ_TEST_FAMILY.identifier.stable_id:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_PROTOCOL_IDENTITY,
                "semantic.test_family",
                ValidationIssueKind.INVALID,
                "identity does not use the registered CMJ test family",
            )
        )
    if identity.semantic.protocol is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_PROTOCOL_IDENTITY,
                "semantic.protocol",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "CMJ protocol identity is missing",
            )
        )
    if acquisition.device is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_DEVICE_IDENTITY,
                "acquisition.device",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "force-platform device/model identity is missing",
            )
        )
    if acquisition.measuring_system is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_MEASURING_SYSTEM,
                "acquisition.measuring_system",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "measuring-system identity is missing",
            )
        )
    _append_acquisition_metadata_issues(issues, acquisition, signal)
    if signal.acquisition_identity_id != identity.identity_id:
        issues.append(
            _issue(
                CMJValidationCode.ACQUISITION_IDENTITY_MISMATCH,
                "signal.acquisition_identity_id",
                ValidationIssueKind.INVALID,
                "signal is linked to a different measurement identity",
            )
        )
    if acquisition.raw_artifact is None:
        issues.append(
            _issue(
                CMJValidationCode.RAW_ARTIFACT_ID_MISMATCH,
                "acquisition.raw_artifact",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "measurement identity has no raw artifact linkage",
            )
        )
    elif acquisition.raw_artifact != signal.source_artifact_id:
        issues.append(
            _issue(
                CMJValidationCode.RAW_ARTIFACT_ID_MISMATCH,
                "acquisition.raw_artifact",
                ValidationIssueKind.INVALID,
                "measurement identity raw artifact does not match signal",
            )
        )
    return _result(issues)


def _append_acquisition_metadata_issues(
    issues: list[CMJValidationIssue],
    acquisition: CMJAcquisitionIdentity,
    signal: RawVerticalForceSignal,
) -> None:
    if acquisition.arrangement is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_ARRANGEMENT,
                "acquisition.arrangement",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition arrangement is missing",
            )
        )
    if acquisition.channel is None or signal.channel_id is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_CHANNEL,
                "acquisition.channel",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "force-platform channel identity is missing",
            )
        )
    elif acquisition.channel.channel_id != signal.channel_id:
        issues.append(
            _issue(
                CMJValidationCode.CHANNEL_MISMATCH,
                "channel",
                ValidationIssueKind.INVALID,
                "signal channel does not match acquisition channel identity",
            )
        )
    if acquisition.acquisition_instance_id is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_ACQUISITION_INSTANCE,
                "acquisition.acquisition_instance_id",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition instance identity is missing",
            )
        )
    elif acquisition.acquisition_instance_id != signal.acquisition_id:
        issues.append(
            _issue(
                CMJValidationCode.ACQUISITION_ID_MISMATCH,
                "signal.acquisition_id",
                ValidationIssueKind.INVALID,
                "signal acquisition ID does not match acquisition identity",
            )
        )
    if (
        acquisition.sensor_channel is not None
        and acquisition.channel is not None
        and acquisition.sensor_channel != acquisition.channel.channel_id
    ):
        issues.append(
            _issue(
                CMJValidationCode.CHANNEL_MISMATCH,
                "acquisition.sensor_channel",
                ValidationIssueKind.INVALID,
                "generic sensor channel and CMJ channel identity disagree",
            )
        )
    _append_arrangement_issues(issues, acquisition)
    if acquisition.physical_axis is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_AXIS,
                "acquisition.physical_axis",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "physical force axis is missing",
            )
        )
    elif not is_registered_axis(acquisition.physical_axis):
        issues.append(
            _issue(
                CMJValidationCode.UNREGISTERED_AXIS,
                "acquisition.physical_axis",
                ValidationIssueKind.INVALID,
                "physical axis reference is not registered as an axis",
            )
        )
    if acquisition.reference_frame is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_REFERENCE_FRAME,
                "acquisition.reference_frame",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "force reference frame is missing",
            )
        )
    elif not is_registered_reference_frame(acquisition.reference_frame):
        issues.append(
            _issue(
                CMJValidationCode.UNREGISTERED_REFERENCE_FRAME,
                "acquisition.reference_frame",
                ValidationIssueKind.INVALID,
                "reference frame is not registered as a reference frame",
            )
        )
    if acquisition.unit is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_UNIT,
                "acquisition.unit",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "force unit is missing",
            )
        )
    elif not is_registered_force_unit(acquisition.unit):
        issues.append(
            _issue(
                CMJValidationCode.UNREGISTERED_UNIT,
                "acquisition.unit",
                ValidationIssueKind.INVALID,
                "force unit is not registered",
            )
        )
    if acquisition.sign_convention is None or (
        acquisition.sign_convention.reference is None
        and acquisition.sign_convention.positive_direction is None
    ):
        issues.append(
            _issue(
                CMJValidationCode.MISSING_SIGN_CONVENTION,
                "acquisition.sign_convention",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "force sign convention is unresolved",
            )
        )
    _append_signal_semantics_issues(issues, acquisition, signal)
    _append_timebase_issues(issues, acquisition, signal)
    if acquisition.acquisition_software_version is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_ACQUISITION_SOFTWARE,
                "acquisition.acquisition_software_version",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition software version is missing",
            )
        )
    if acquisition.acquisition_timestamp is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_ACQUISITION_TIMESTAMP,
                "acquisition.acquisition_timestamp",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition timestamp is missing",
            )
        )
    if acquisition.processing_state is SignalProcessingState.UNKNOWN:
        issues.append(
            _issue(
                CMJValidationCode.PROCESSING_STATE_UNKNOWN,
                "acquisition.processing_state",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition preprocessing state is unresolved",
            )
        )
    if signal.processing_state is not SignalProcessingState.UNKNOWN and (
        acquisition.processing_state is not SignalProcessingState.UNKNOWN
        and acquisition.processing_state is not signal.processing_state
    ):
        issues.append(
            _issue(
                CMJValidationCode.PROCESSING_STATE_MISMATCH,
                "processing_state",
                ValidationIssueKind.INVALID,
                "signal and acquisition processing states disagree",
            )
        )
    if acquisition.calibration.status is ReferenceState.UNKNOWN:
        issues.append(
            _issue(
                CMJValidationCode.CALIBRATION_STATE_UNKNOWN,
                "acquisition.calibration.status",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "calibration/reference state is unresolved",
            )
        )
    if acquisition.zeroing.status is ReferenceState.UNKNOWN:
        issues.append(
            _issue(
                CMJValidationCode.ZEROING_STATE_UNKNOWN,
                "acquisition.zeroing.status",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "zeroing/tare state is unresolved",
            )
        )


def _append_signal_semantics_issues(
    issues: list[CMJValidationIssue],
    acquisition: CMJAcquisitionIdentity,
    signal: RawVerticalForceSignal,
) -> None:
    pairs: tuple[tuple[str, object | None, object | None], ...] = (
        ("unit", acquisition.unit, signal.unit),
        ("physical_axis", acquisition.physical_axis, signal.physical_axis),
        ("reference_frame", acquisition.reference_frame, signal.reference_frame),
        ("sign_convention", acquisition.sign_convention, signal.sign_convention),
    )
    for field_name, identity_value, signal_value in pairs:
        if signal_value is None:
            issues.append(
                _issue(
                    CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH,
                    f"signal.{field_name}",
                    ValidationIssueKind.INSUFFICIENT_INFORMATION,
                    f"signal {field_name} semantics are missing",
                )
            )
        elif identity_value is not None and not _same_semantics(identity_value, signal_value):
            issues.append(
                _issue(
                    CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH,
                    field_name,
                    ValidationIssueKind.INVALID,
                    f"signal and acquisition {field_name} semantics disagree",
                )
            )


def _same_semantics(left: object, right: object) -> bool:
    """Compare registry semantics by stable identity, not display metadata."""

    if isinstance(left, SignConvention) and isinstance(right, SignConvention):
        left_reference = getattr(getattr(left.reference, "identifier", None), "stable_id", None)
        right_reference = getattr(getattr(right.reference, "identifier", None), "stable_id", None)
        return left_reference == right_reference and (
            left.positive_direction == right.positive_direction
        )
    left_identifier = getattr(getattr(left, "identifier", None), "stable_id", None)
    right_identifier = getattr(getattr(right, "identifier", None), "stable_id", None)
    return left_identifier is not None and left_identifier == right_identifier


def _append_timebase_issues(
    issues: list[CMJValidationIssue],
    acquisition: CMJAcquisitionIdentity,
    signal: RawVerticalForceSignal,
) -> None:
    if acquisition.timebase is None:
        issues.append(
            _issue(
                CMJValidationCode.MISSING_TIMEBASE,
                "acquisition.timebase",
                ValidationIssueKind.INSUFFICIENT_INFORMATION,
                "acquisition timebase semantics are missing",
            )
        )
        return
    if signal.timebase is None:
        return
    if (
        acquisition.timebase.kind is TimebaseKind.REGULAR
        and not isinstance(signal.timebase, RegularTimebase)
    ) or (
        acquisition.timebase.kind is TimebaseKind.EXPLICIT
        and not isinstance(signal.timebase, ExplicitTimebase)
    ):
        issues.append(
            _issue(
                CMJValidationCode.TIMEBASE_KIND_MISMATCH,
                "timebase.kind",
                ValidationIssueKind.INVALID,
                "signal and acquisition timebase kinds disagree",
            )
        )
        return
    declared_rates = [
        rate
        for rate in (
            acquisition.timebase.sample_rate_hz,
            acquisition.sampling.frequency_hz if acquisition.sampling is not None else None,
        )
        if rate is not None
    ]
    if isinstance(signal.timebase, RegularTimebase):
        declared_rates.append(signal.timebase.sample_rate_hz)
    elif len(signal.timebase.times_s) >= 2 and all(
        isinstance(time, int | float) and not isinstance(time, bool) and math.isfinite(time)
        for time in signal.timebase.times_s
    ):
        intervals = tuple(
            right - left
            for left, right in zip(
                signal.timebase.times_s, signal.timebase.times_s[1:], strict=False
            )
            if math.isfinite(left) and math.isfinite(right) and right > left
        )
        if intervals and all(math.isclose(interval, intervals[0]) for interval in intervals):
            declared_rates.append(1.0 / intervals[0])
    if declared_rates and not all(
        _same_rate(declared_rates[0], rate) for rate in declared_rates[1:]
    ):
        issues.append(
            _issue(
                CMJValidationCode.DECLARED_SAMPLE_RATE_MISMATCH,
                "timebase.sample_rate_hz",
                ValidationIssueKind.INVALID,
                "declared sampling rates do not agree",
            )
        )


def _append_arrangement_issues(
    issues: list[CMJValidationIssue],
    acquisition: CMJAcquisitionIdentity,
) -> None:
    arrangement = acquisition.arrangement
    if arrangement is None:
        return
    channel = acquisition.channel
    roles = {item.role for item in acquisition.available_channels}
    channel_ids = [item.channel_id for item in acquisition.available_channels]
    if len(channel_ids) != len(set(channel_ids)):
        issues.append(
            _issue(
                CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                "acquisition.available_channels",
                ValidationIssueKind.INVALID,
                "available channel IDs must be unique",
            )
        )
    if (
        channel is not None
        and acquisition.available_channels
        and channel not in acquisition.available_channels
    ):
        issues.append(
            _issue(
                CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                "acquisition.channel",
                ValidationIssueKind.INVALID,
                "selected channel must be one of available channels",
            )
        )
    expected_role = {
        AcquisitionArrangement.LEFT_FORCE_PLATFORM: "LEFT_FORCE_PLATFORM",
        AcquisitionArrangement.RIGHT_FORCE_PLATFORM: "RIGHT_FORCE_PLATFORM",
        AcquisitionArrangement.SINGLE_PLATFORM: "SINGLE_FORCE_PLATFORM",
    }.get(arrangement)
    if expected_role is not None and channel is not None and channel.role.value != expected_role:
        issues.append(
            _issue(
                CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                "acquisition.channel.role",
                ValidationIssueKind.INVALID,
                "selected channel role does not match acquisition arrangement",
            )
        )
    if arrangement is AcquisitionArrangement.BILATERAL_SEPARATE:
        if not {
            "LEFT_FORCE_PLATFORM",
            "RIGHT_FORCE_PLATFORM",
        } <= {role.value for role in roles}:
            issues.append(
                _issue(
                    CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                    "acquisition.available_channels",
                    ValidationIssueKind.INSUFFICIENT_INFORMATION,
                    "bilateral separate acquisition must retain left and right channels",
                )
            )
        if channel is not None and channel.role.value not in {
            "LEFT_FORCE_PLATFORM",
            "RIGHT_FORCE_PLATFORM",
        }:
            issues.append(
                _issue(
                    CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                    "acquisition.channel.role",
                    ValidationIssueKind.INVALID,
                    "bilateral separate signal must identify one separate platform channel",
                )
            )
        if acquisition.combination_lineage is not None:
            issues.append(
                _issue(
                    CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                    "acquisition.combination_lineage",
                    ValidationIssueKind.INVALID,
                    "bilateral separate acquisition cannot carry a hidden combination lineage",
                )
            )
    elif arrangement is AcquisitionArrangement.BILATERAL_PRECOMBINED:
        if channel is not None and channel.role.value != "PRECOMBINED_VERTICAL_FORCE":
            issues.append(
                _issue(
                    CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT,
                    "acquisition.channel.role",
                    ValidationIssueKind.INVALID,
                    "pre-combined acquisition must identify a combined channel",
                )
            )
        lineage = acquisition.combination_lineage
        if lineage is None:
            issues.append(
                _issue(
                    CMJValidationCode.COMBINATION_LINEAGE_MISSING,
                    "acquisition.combination_lineage",
                    ValidationIssueKind.INSUFFICIENT_INFORMATION,
                    "pre-combined output must identify how bilateral force was combined",
                )
            )
        elif (
            (
                lineage.kind is CombinationLineageKind.DIRECT_COMBINED_OUTPUT
                and acquisition.processing_state is not SignalProcessingState.RAW_ACQUIRED
            )
            or (
                lineage.kind is CombinationLineageKind.VENDOR_COMBINED_OUTPUT
                and acquisition.processing_state is not SignalProcessingState.DEVICE_PROCESSED
            )
            or (
                lineage.kind is CombinationLineageKind.DYNAMISLM_COMBINED_OUTPUT
                and acquisition.processing_state is not SignalProcessingState.SYSTEM_PROCESSED
            )
        ):
            issues.append(
                _issue(
                    CMJValidationCode.COMBINATION_STATE_MISMATCH,
                    "acquisition.processing_state",
                    ValidationIssueKind.INVALID,
                    "combination lineage and processing state disagree",
                )
            )
    elif arrangement is AcquisitionArrangement.OTHER_REGISTERED_ARRANGEMENT:
        if acquisition.arrangement_reference is None:
            issues.append(
                _issue(
                    CMJValidationCode.MISSING_ARRANGEMENT_REFERENCE,
                    "acquisition.arrangement_reference",
                    ValidationIssueKind.INSUFFICIENT_INFORMATION,
                    "other arrangement must identify its registered arrangement",
                )
            )
        elif not is_registered_arrangement(acquisition.arrangement_reference):
            issues.append(
                _issue(
                    CMJValidationCode.UNREGISTERED_ARRANGEMENT_REFERENCE,
                    "acquisition.arrangement_reference",
                    ValidationIssueKind.INVALID,
                    "other arrangement reference is not registered",
                )
            )


def _result(issues: list[CMJValidationIssue]) -> CMJValidationResult:
    if any(issue.kind is ValidationIssueKind.INVALID for issue in issues):
        status = ValidationStatus.INVALID
    elif issues:
        status = ValidationStatus.INSUFFICIENT_INFORMATION
    else:
        status = ValidationStatus.VALID
    return CMJValidationResult(status=status, issues=tuple(issues))
