"""Verifier-ready deterministic reference cases for RES-71.

The interface stores typed case contracts and expected outputs/refusals.  It
does not execute an LM or accept an LM-produced numeric answer as authority.
Later verifier work can bind these cases to the already-registered operation
dispatch surface.
"""

from __future__ import annotations

from dynamislm.qualification.contracts import (
    ReferenceCase,
    ReferenceCaseStatus,
    ReferenceValue,
)
from dynamislm.serialization import canonical_hash, canonical_json

RES71_REFERENCE_INTERFACE_VERSION = "1.0.0"


def _operation(key: str, version: str = "1.0.0") -> str:
    return f"dynamislm:registered-operation:{key}@{version}"


def _value(name: str, value: bool | float | int | str, unit: str | None = None) -> ReferenceValue:
    return ReferenceValue(name=name, value=value, unit=unit)


def _cases() -> tuple[ReferenceCase, ...]:
    return (
        ReferenceCase(
            case_id="res71-external-unit-km-to-m",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="external-load",
            operation_id=_operation("unit-normalization"),
            status=ReferenceCaseStatus.VALUE,
            synthetic_input=(
                _value("value", 1.0),
                _value("from_unit", "kilometer"),
                _value("to_unit", "meter"),
            ),
            expected_values=(_value("value", 1000.0, "m"),),
            expected_refusal_class=None,
            expected_reason_codes=(),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=0.0,
            tolerance_relative=0.0,
            required_provenance_fields=("operation_id", "unit", "method_registry_version"),
            authority_references=(
                "docs/decisions/RES64-DR-001-external-load-scientific-identity.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-external-relative-distance",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="external-load",
            operation_id=_operation("duration-normalized-distance"),
            status=ReferenceCaseStatus.VALUE,
            synthetic_input=(
                _value("total_distance", 600.0, "m"),
                _value("valid_duration", 10.0, "min"),
            ),
            expected_values=(_value("relative_distance", 60.0, "m/min"),),
            expected_refusal_class=None,
            expected_reason_codes=(),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=0.0,
            tolerance_relative=0.0,
            required_provenance_fields=(
                "operation_id",
                "source_observation_ids",
                "processing_run_id",
            ),
            authority_references=(
                "docs/decisions/RES64-DR-001-external-load-scientific-identity.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-cmj-flight-time-v2-gold",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="CMJ",
            operation_id=_operation("cmj-flight-time-ballistic-jump-height-v2", "2.0.0"),
            status=ReferenceCaseStatus.VALUE,
            synthetic_input=(
                _value("flight_time_s", 0.5, "s"),
                _value("gravity_m_per_s2", 9.81, "m/s2"),
            ),
            expected_values=(_value("jump_height_m", 0.3065625, "m"),),
            expected_refusal_class=None,
            expected_reason_codes=(),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=1e-12,
            tolerance_relative=1e-12,
            required_provenance_fields=(
                "source_observation_id",
                "takeoff_event_id",
                "landing_event_id",
                "operation_id",
                "processing_run_id",
            ),
            authority_references=("docs/decisions/RES65-DR-001-cmj-football-metric-completion.md",),
        ),
        ReferenceCase(
            case_id="res71-rsa-mechanical-percent-decrement",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="RSA",
            operation_id=_operation("rsa-percent-decrement-s-dec-v1"),
            status=ReferenceCaseStatus.VALUE,
            synthetic_input=(
                _value("repetition_times_s", "[1.0, 1.1, 1.2]"),
                _value("best_time_s", 1.0, "s"),
            ),
            expected_values=(_value("s_dec_percent", 10.0, "%"),),
            expected_refusal_class=None,
            expected_reason_codes=(),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=1e-12,
            tolerance_relative=1e-12,
            required_provenance_fields=("protocol_identity", "criterion_sprint", "operation_id"),
            authority_references=(
                "docs/decisions/RES67-DR-001-field-testing-scientific-engine.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-longitudinal-absolute-change",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="longitudinal-statistics",
            operation_id=_operation("longitudinal-absolute-change-v1"),
            status=ReferenceCaseStatus.VALUE,
            synthetic_input=(
                _value("baseline", 10.0),
                _value("followup", 15.0),
                _value("support", "exactly-two-comparable-within-athlete-entries"),
            ),
            expected_values=(_value("absolute_change", 5.0),),
            expected_refusal_class=None,
            expected_reason_codes=(),
            expected_comparability_state=None,
            expected_claim_level="NUMERICAL_CHANGE",
            tolerance_absolute=0.0,
            tolerance_relative=0.0,
            required_provenance_fields=("support_hash", "operation_id", "source_observation_ids"),
            authority_references=(
                "docs/decisions/RES69-DR-001-longitudinal-reliability-uncertainty.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-nonfinite-unit-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="external-load",
            operation_id=_operation("unit-normalization"),
            status=ReferenceCaseStatus.REFUSAL,
            synthetic_input=(
                _value("value", "NaN"),
                _value("from_unit", "meter"),
                _value("to_unit", "kilometer"),
            ),
            expected_values=(),
            expected_refusal_class="COMPUTATION_NOT_REGISTERED",
            expected_reason_codes=("NONFINITE_INPUT",),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=("blocked_claim", "reason_codes", "missing_information"),
            authority_references=(
                "docs/decisions/RES64-DR-001-external-load-scientific-identity.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-cmj-rfd-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="CMJ",
            operation_id=None,
            status=ReferenceCaseStatus.REFUSAL,
            synthetic_input=(_value("requested_operation", "CMJ RFD"),),
            expected_values=(),
            expected_refusal_class="COMPUTATION_NOT_REGISTERED",
            expected_reason_codes=("NO_REGISTERED_OPERATION",),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=(
                "blocked_claim",
                "reason_codes",
                "what_can_still_be_safely_described",
            ),
            authority_references=("docs/decisions/RES65-RECEIPT.json",),
        ),
        ReferenceCase(
            case_id="res71-bpt-generic-power-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="bench-press-throw",
            operation_id=None,
            status=ReferenceCaseStatus.REFUSAL,
            synthetic_input=(_value("load", 80.0, "kg"), _value("velocity", 1.2, "m/s")),
            expected_values=(),
            expected_refusal_class="COMPUTATION_NOT_REGISTERED",
            expected_reason_codes=("NO_REGISTERED_OPERATION", "COMPUTATION_NOT_REGISTERED"),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=("blocked_claim", "reason_codes", "safe_descriptions"),
            authority_references=("docs/decisions/RES68-RECEIPT.json",),
        ),
        ReferenceCase(
            case_id="res71-bpt-mpv-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="bench-press-throw",
            operation_id=_operation("bench-press-throw-mean-propulsive-velocity-v1"),
            status=ReferenceCaseStatus.REFUSAL,
            synthetic_input=(
                _value("support", "provider-or-series-support-without-registered-MPV"),
            ),
            expected_values=(),
            expected_refusal_class="COMPUTATION_NOT_REGISTERED",
            expected_reason_codes=("NO_REGISTERED_OPERATION", "COMPUTATION_NOT_REGISTERED"),
            expected_comparability_state=None,
            expected_claim_level=None,
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=("blocked_claim", "reason_codes", "safe_descriptions"),
            authority_references=("docs/decisions/RES68-RECEIPT.json",),
        ),
        ReferenceCase(
            case_id="res71-same-label-different-method",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="cross-source-comparability",
            operation_id=None,
            status=ReferenceCaseStatus.COMPARABILITY,
            synthetic_input=(
                _value("left_label", "HSR distance"),
                _value("right_label", "HSR distance"),
                _value("difference", "threshold identity / provider processing"),
            ),
            expected_values=(),
            expected_refusal_class=None,
            expected_reason_codes=("THRESHOLD_MISMATCH", "METHOD_MISMATCH"),
            expected_comparability_state="NOT_COMPARABLE",
            expected_claim_level=None,
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=("request_hash", "dimension_findings", "rule_registry_hash"),
            authority_references=(
                "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
            ),
        ),
        ReferenceCase(
            case_id="res71-causal-overclaim-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="claim-authority",
            operation_id=None,
            status=ReferenceCaseStatus.CLAIM_AUTHORITY,
            synthetic_input=(_value("requested_claim", "observed change caused fatigue"),),
            expected_values=(),
            expected_refusal_class="CAUSAL_IDENTIFICATION_UNSUPPORTED",
            expected_reason_codes=("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
            expected_comparability_state=None,
            expected_claim_level="OBSERVED_VALUE_ONLY",
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=(
                "claim_intent_hash",
                "blocked_claims",
                "safe_observation_description",
            ),
            authority_references=("docs/architecture/REASONING_CLAIMS_EVALUATION_V1.md",),
        ),
        ReferenceCase(
            case_id="res71-between-to-within-refusal",
            case_version=RES71_REFERENCE_INTERFACE_VERSION,
            family="analysis-capability",
            operation_id=None,
            status=ReferenceCaseStatus.CLAIM_AUTHORITY,
            synthetic_input=(
                _value("requested_estimand", "within-athlete"),
                _value("support", "one-row-per-athlete"),
            ),
            expected_values=(),
            expected_refusal_class="ANALYSIS_DESIGN_MISMATCH",
            expected_reason_codes=("RES70_WRONG_LEVEL_OF_ANALYSIS",),
            expected_comparability_state=None,
            expected_claim_level="BETWEEN_ATHLETE_NOT_WITHIN_ATHLETE",
            tolerance_absolute=None,
            tolerance_relative=None,
            required_provenance_fields=("support_hash", "resolved_level", "refusal_reasons"),
            authority_references=(
                "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
            ),
        ),
    )


def get_reference_cases() -> tuple[ReferenceCase, ...]:
    """Return the immutable reference-case set."""

    return _cases()


def get_reference_case(case_id: str) -> ReferenceCase:
    """Resolve one case by stable ID."""

    for case in get_reference_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(case_id)


def validate_reference_cases(cases: tuple[ReferenceCase, ...] | None = None) -> None:
    if cases is None:
        cases = get_reference_cases()
    ids = tuple(case.case_id for case in cases)
    if len(set(ids)) != len(ids):
        raise ValueError("RES-71 reference cases must have unique case IDs")
    if not any(case.status is ReferenceCaseStatus.VALUE for case in cases):
        raise ValueError("reference set needs a value case")
    if not any(case.status is ReferenceCaseStatus.REFUSAL for case in cases):
        raise ValueError("reference set needs a refusal case")
    if not any(case.status is ReferenceCaseStatus.COMPARABILITY for case in cases):
        raise ValueError("reference set needs a comparability case")
    if not any(case.status is ReferenceCaseStatus.CLAIM_AUTHORITY for case in cases):
        raise ValueError("reference set needs a claim-authority case")
    for case in cases:
        if case.operation_id is not None and not case.operation_id.startswith(
            "dynamislm:registered-operation:"
        ):
            raise ValueError(f"invalid operation identity in {case.case_id}")


def reference_case_manifest(cases: tuple[ReferenceCase, ...] | None = None) -> str:
    """Return canonical JSON suitable for a later verifier artifact."""

    if cases is None:
        cases = get_reference_cases()
    validate_reference_cases(cases)
    return canonical_json(cases)


def reference_case_digest(cases: tuple[ReferenceCase, ...] | None = None) -> str:
    """Return the deterministic digest of the reference interface."""

    if cases is None:
        cases = get_reference_cases()
    validate_reference_cases(cases)
    return canonical_hash(cases)


__all__ = [
    "RES71_REFERENCE_INTERFACE_VERSION",
    "get_reference_case",
    "get_reference_cases",
    "reference_case_digest",
    "reference_case_manifest",
    "validate_reference_cases",
]
