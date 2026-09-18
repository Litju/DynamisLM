"""Narrow source-bound method comparison and Bland-Altman V1 authority."""

from __future__ import annotations

import math
from dataclasses import replace

from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
)
from dynamislm.longitudinal.statistics.models import (
    AuthorityStatus,
    MethodComparisonDesignAuthority,
    MethodComparisonDesignEvidence,
    MethodComparisonMethodKeyV1,
    MethodComparisonPair,
    RepeatedPairPolicy,
    RES69ReasonCode,
    StatisticalNonComputable,
    StatisticalObservationReference,
    StatisticalResult,
    StatisticalSourceRecordReference,
    StatisticalSupport,
)
from dynamislm.longitudinal.statistics.registry import (
    RES69_B_MINUS_A_SIGN_CONVENTION,
    RES69_BA_BIAS_ESTIMAND,
    RES69_BA_ESTIMATOR,
    RES69_BA_SD_DIFFERENCE_ESTIMAND,
    RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    RES69_METHOD_COMPARISON_OCCASION_POLICY,
    RES69_METHOD_COMPARISON_OPERATION,
    RES69_REGISTRY_VERSION,
)
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    scalar_value,
    validate_statistical_support,
)
from dynamislm.longitudinal.statistics.validation import (
    make_estimate,
    make_result,
    refusal,
    refusal_for_exception,
    validate_method_comparison_authority,
)
from dynamislm.measurement.identity import (
    MetadataEntry,
    RegistryReference,
    UnitReference,
)
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import RefusalResult
from dynamislm.serialization import canonical_hash


def _parameters(*items: tuple[str, str | int | float]) -> tuple[MetadataEntry, ...]:
    return tuple(MetadataEntry(key, value) for key, value in items)


def build_method_comparison_design_evidence(
    *,
    support: StatisticalSupport,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    design_identity: RegistryReference,
    pairs: tuple[MethodComparisonPair, ...],
    method_a_key: MethodComparisonMethodKeyV1,
    method_b_key: MethodComparisonMethodKeyV1,
    target_construct: RegistryReference,
    target_measurand: RegistryReference,
    metric_a_definition: RegistryReference,
    metric_b_definition: RegistryReference,
    unit_a: UnitReference,
    unit_b: UnitReference,
    evidence_references: tuple[EvidenceReference, ...],
    producing_method: RegistryReference,
    occasion_context_policy: RegistryReference = RES69_METHOD_COMPARISON_OCCASION_POLICY,
    sign_convention: RegistryReference = RES69_B_MINUS_A_SIGN_CONVENTION,
    hidden_transformation: bool = False,
    repeated_pair_policy: RepeatedPairPolicy = RepeatedPairPolicy.ONE_PAIR_PER_INDEPENDENT_SUBJECT,
    registry_version: str = RES69_REGISTRY_VERSION,
) -> MethodComparisonDesignEvidence:
    """Create typed method-comparison evidence before authority normalization."""

    return MethodComparisonDesignEvidence(
        support=support,
        source_records=source_records,
        design_identity=design_identity,
        pairs=pairs,
        method_a_key=method_a_key,
        method_b_key=method_b_key,
        target_construct=target_construct,
        target_measurand=target_measurand,
        metric_a_definition=metric_a_definition,
        metric_b_definition=metric_b_definition,
        unit_a=unit_a,
        unit_b=unit_b,
        occasion_context_policy=occasion_context_policy,
        sign_convention=sign_convention,
        hidden_transformation=hidden_transformation,
        repeated_pair_policy=repeated_pair_policy,
        evidence_references=evidence_references,
        producing_method=producing_method,
        registry_version=registry_version,
    )


def _validate_method_comparison_evidence(evidence: MethodComparisonDesignEvidence) -> None:
    support = evidence.support
    validate_statistical_support(support)
    expected_records = tuple(
        sorted(
            (
                StatisticalSourceRecordReference.from_record(record)
                for record in evidence.source_records
            ),
            key=lambda item: item.record_id.qualified,
        )
    )
    if expected_records != support.source_records:
        raise StatisticalConstraintError(
            "method-comparison source records do not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if evidence.producing_method != RES69_METHOD_COMPARISON_DESIGN_OPERATION:
        raise StatisticalConstraintError(
            "method comparison evidence must use the registered design-normalization operation",
            RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
        )
    if evidence.registry_version != RES69_REGISTRY_VERSION:
        raise StatisticalConstraintError(
            "method comparison registry version is not the registered RES-69 version",
            RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
        )
    if evidence.sign_convention != RES69_B_MINUS_A_SIGN_CONVENTION:
        raise StatisticalConstraintError(
            "method comparison requires the registered B minus A sign convention",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    if evidence.occasion_context_policy != RES69_METHOD_COMPARISON_OCCASION_POLICY:
        raise StatisticalConstraintError(
            "method comparison context policy is not registered",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    if evidence.repeated_pair_policy is not RepeatedPairPolicy.ONE_PAIR_PER_INDEPENDENT_SUBJECT:
        raise StatisticalConstraintError(
            "repeated-pair policy is not the V1 independent-subject policy",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    if evidence.hidden_transformation:
        raise StatisticalConstraintError(
            "hidden transformation is not admissible for simple BA V1",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    if evidence.unit_a != evidence.unit_b:
        raise StatisticalConstraintError(
            "method comparison requires exact common units; conversion is not registered",
            RES69ReasonCode.UNIT_MISMATCH.value,
        )
    entries = {entry.canonical_entry_id: entry for entry in support.included_entries}
    paired_ids: set[object] = set()
    athletes: set[object] = set()
    for pair in evidence.pairs:
        method_a = entries.get(pair.method_a.entry_id)
        method_b = entries.get(pair.method_b.entry_id)
        if method_a is None or method_b is None:
            raise StatisticalConstraintError(
                "method comparison pair is incomplete",
                RES69ReasonCode.INCOMPLETE_PAIR.value,
            )
        if (
            StatisticalObservationReference.from_entry(method_a) != pair.method_a
            or StatisticalObservationReference.from_entry(method_b) != pair.method_b
        ):
            raise StatisticalConstraintError(
                "method comparison pairing hashes do not match support",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        method_a_unit = scalar_value(method_a)[1]
        method_b_unit = scalar_value(method_b)[1]
        actual_method_a_key = MethodComparisonMethodKeyV1.from_measurement_identity(
            method_a.observation.identity,
            method_a_unit,
        )
        actual_method_b_key = MethodComparisonMethodKeyV1.from_measurement_identity(
            method_b.observation.identity,
            method_b_unit,
        )
        if (
            actual_method_a_key != evidence.method_a_key
            or actual_method_b_key != evidence.method_b_key
        ):
            raise StatisticalConstraintError(
                "method comparison authority does not match stable method keys",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        if method_a.session_id != method_b.session_id:
            raise StatisticalConstraintError(
                "method A and method B must be observed in the same declared occasion",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        if (
            method_a.observation.identity.semantic.construct.stable_id
            != evidence.target_construct.stable_id
            or method_b.observation.identity.semantic.construct.stable_id
            != evidence.target_construct.stable_id
        ):
            raise StatisticalConstraintError(
                "method comparison construct mismatch",
                RES69ReasonCode.IDENTITY_UNRESOLVED.value,
            )
        if (
            method_a.observation.identity.semantic.measurand.stable_id
            != evidence.target_measurand.stable_id
            or method_b.observation.identity.semantic.measurand.stable_id
            != evidence.target_measurand.stable_id
        ):
            raise StatisticalConstraintError(
                "method comparison measurand mismatch",
                RES69ReasonCode.IDENTITY_UNRESOLVED.value,
            )
        if (
            method_a.observation.identity.semantic.metric_definition.stable_id
            != evidence.metric_a_definition.stable_id
            or method_b.observation.identity.semantic.metric_definition.stable_id
            != evidence.metric_b_definition.stable_id
        ):
            raise StatisticalConstraintError(
                "method comparison metric identities do not match evidence",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        unit_a = method_a_unit
        unit_b = method_b_unit
        if unit_a != evidence.unit_a or unit_b != evidence.unit_b:
            raise StatisticalConstraintError(
                "method comparison units do not match evidence",
                RES69ReasonCode.UNIT_MISMATCH.value,
            )
        paired_ids.update((pair.method_a.entry_id, pair.method_b.entry_id))
        if pair.athlete_id in athletes:
            raise StatisticalConstraintError(
                "repeated observations were flattened into one method-comparison pair",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        athletes.add(pair.athlete_id)
    if paired_ids != {entry.canonical_entry_id for entry in support.included_entries}:
        raise StatisticalConstraintError(
            "method comparison support contains an incomplete or unpaired observation",
            RES69ReasonCode.INCOMPLETE_PAIR.value,
        )


def build_method_comparison_design_authority(
    evidence: MethodComparisonDesignEvidence,
) -> MethodComparisonDesignAuthority:
    """Normalize source/protocol evidence into a source-bound BA authority."""

    if not isinstance(evidence, MethodComparisonDesignEvidence):
        raise ValueError("evidence must be a MethodComparisonDesignEvidence")
    _validate_method_comparison_evidence(evidence)
    support = evidence.support
    source_records = tuple(
        sorted(
            (
                StatisticalSourceRecordReference.from_record(record)
                for record in evidence.source_records
            ),
            key=lambda item: item.record_id.qualified,
        )
    )
    authority = MethodComparisonDesignAuthority(
        support_id=support.canonical_support_id,
        support_hash=support.canonical_support_hash,
        analysis_input_ids=support.input_ids,
        analysis_input_hashes=support.input_hashes,
        source_records=source_records,
        source_artifacts=support.source_artifacts,
        source_provenance=support.source_provenance,
        design_identity=evidence.design_identity,
        pairs=tuple(sorted(evidence.pairs, key=lambda item: item.pair_id.qualified)),
        method_a_key=evidence.method_a_key,
        method_b_key=evidence.method_b_key,
        target_construct=evidence.target_construct,
        target_measurand=evidence.target_measurand,
        metric_a_definition=evidence.metric_a_definition,
        metric_b_definition=evidence.metric_b_definition,
        unit_a=evidence.unit_a,
        unit_b=evidence.unit_b,
        occasion_context_policy=evidence.occasion_context_policy,
        sign_convention=evidence.sign_convention,
        hidden_transformation=evidence.hidden_transformation,
        repeated_pair_policy=evidence.repeated_pair_policy,
        evidence_references=evidence.evidence_references,
        producing_method=evidence.producing_method,
        registry_version=evidence.registry_version,
        source_evidence_hash=canonical_hash(evidence),
        authority_status=AuthorityStatus.UNVERIFIED,
    )
    return replace(
        authority,
        authority_status=AuthorityStatus.SOURCE_BOUND,
        authority_token=canonical_hash(
            {
                "authority_hash": authority.canonical_authority_hash,
                "purpose": "RES69_SOURCE_BOUND_AUTHORITY_V1",
            }
        ),
    )


def _validated_method_pairs(
    support: StatisticalSupport,
    authority: MethodComparisonDesignAuthority,
) -> tuple[
    tuple[
        MethodComparisonPair,
        LongitudinalObservationEntry,
        LongitudinalObservationEntry,
        float,
        float,
    ],
    ...,
]:
    validate_method_comparison_authority(authority, support)
    validate_statistical_support(support)
    if (
        authority.analysis_input_ids != support.input_ids
        or authority.analysis_input_hashes != support.input_hashes
    ):
        raise StatisticalConstraintError(
            "method-comparison authority input lineage does not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if authority.source_records != support.source_records:
        raise StatisticalConstraintError(
            "method-comparison authority source records do not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if (
        authority.source_artifacts != support.source_artifacts
        or authority.source_provenance != support.source_provenance
    ):
        raise StatisticalConstraintError(
            "method-comparison authority provenance does not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if authority.sign_convention != RES69_B_MINUS_A_SIGN_CONVENTION:
        raise StatisticalConstraintError(
            "method-comparison sign convention is not registered",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    if authority.hidden_transformation:
        raise StatisticalConstraintError(
            "hidden transformation is not admissible for simple BA V1",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    entries = {entry.canonical_entry_id: entry for entry in support.included_entries}
    seen_entries: set[object] = set()
    seen_athletes: set[object] = set()
    validated = []
    for pair in authority.pairs:
        method_a = entries.get(pair.method_a.entry_id)
        method_b = entries.get(pair.method_b.entry_id)
        if method_a is None or method_b is None:
            raise StatisticalConstraintError(
                "method-comparison pair is incomplete",
                RES69ReasonCode.INCOMPLETE_PAIR.value,
            )
        if (
            StatisticalObservationReference.from_entry(method_a) != pair.method_a
            or StatisticalObservationReference.from_entry(method_b) != pair.method_b
        ):
            raise StatisticalConstraintError(
                "method-comparison source observation hash does not match support",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        a_value, a_unit = scalar_value(method_a)
        b_value, b_unit = scalar_value(method_b)
        actual_method_a_key = MethodComparisonMethodKeyV1.from_measurement_identity(
            method_a.observation.identity,
            a_unit,
        )
        actual_method_b_key = MethodComparisonMethodKeyV1.from_measurement_identity(
            method_b.observation.identity,
            b_unit,
        )
        if (
            actual_method_a_key != authority.method_a_key
            or actual_method_b_key != authority.method_b_key
        ):
            raise StatisticalConstraintError(
                "method-comparison stable method key does not match pair support",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        if method_a.session_id != method_b.session_id:
            raise StatisticalConstraintError(
                "method A and method B must be observed in the same declared occasion",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        if pair.athlete_id in seen_athletes:
            raise StatisticalConstraintError(
                "repeated pair flattening is not allowed",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        if a_unit != authority.unit_a or b_unit != authority.unit_b or a_unit != b_unit:
            raise StatisticalConstraintError(
                "method-comparison arithmetic requires exact common units",
                RES69ReasonCode.UNIT_MISMATCH.value,
            )
        seen_entries.update((pair.method_a.entry_id, pair.method_b.entry_id))
        seen_athletes.add(pair.athlete_id)
        validated.append((pair, method_a, method_b, a_value, b_value))
    if seen_entries != {entry.canonical_entry_id for entry in support.included_entries}:
        raise StatisticalConstraintError(
            "method comparison has an incomplete pair support",
            RES69ReasonCode.INCOMPLETE_PAIR.value,
        )
    return tuple(validated)


def _sample_sd(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        raise ValueError("sample SD requires at least two values")
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def calculate_bland_altman_summary(
    support: StatisticalSupport,
    authority: object,
) -> StatisticalResult | RefusalResult:
    """Calculate only B-minus-A bias and sample SD of differences."""

    claim = "calculate simple Bland-Altman V1 bias and SD difference"
    try:
        if not isinstance(authority, MethodComparisonDesignAuthority):
            raise StatisticalConstraintError(
                "source-bound MethodComparisonDesignAuthority is required",
                RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
            )
        pairs = _validated_method_pairs(support, authority)
        differences = tuple(item[4] - item[3] for item in pairs)
        bias = math.fsum(differences) / len(differences)
        parameters = _parameters(
            ("pair_count", len(pairs)),
            ("support_hash", support.canonical_support_hash),
            ("authority_hash", authority.canonical_authority_hash),
            ("sign_convention", RES69_B_MINUS_A_SIGN_CONVENTION.stable_id),
        )
        estimates = [
            make_estimate(
                estimand=RES69_BA_BIAS_ESTIMAND,
                value=bias,
                unit=authority.unit_a,
                estimator=RES69_BA_ESTIMATOR,
                parameters=parameters,
            )
        ]
        non_computable: tuple[StatisticalNonComputable, ...] = ()
        if len(differences) >= 2:
            estimates.append(
                make_estimate(
                    estimand=RES69_BA_SD_DIFFERENCE_ESTIMAND,
                    value=_sample_sd(differences),
                    unit=authority.unit_a,
                    estimator=RES69_BA_ESTIMATOR,
                    parameters=parameters,
                )
            )
        else:
            from dynamislm.longitudinal.statistics.models import StatisticalOperationDisposition

            non_computable = (
                StatisticalNonComputable(
                    RES69_METHOD_COMPARISON_OPERATION,
                    StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
                    "sample SD of method differences requires N >= 2 independent pairs",
                ),
            )
        return make_result(
            support,
            operation=RES69_METHOD_COMPARISON_OPERATION,
            estimator=RES69_BA_ESTIMATOR,
            estimates=tuple(estimates),
            parameters=parameters,
            authority_references=(authority.design_identity, authority.producing_method),
            authority_hashes=(authority.canonical_authority_hash,),
            non_computable=non_computable,
            evidence_references=authority.evidence_references,
            registry_version=authority.registry_version,
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def request_classical_bland_altman_limits(
    support: StatisticalSupport | None = None,
    authority: object | None = None,
) -> RefusalResult:
    """Return the registered-not-computable outcome for classical BA LoA."""

    del authority
    return refusal(
        "calculate classical Bland-Altman limits of agreement",
        RES69ReasonCode.CLASSICAL_LOA_DEFERRED,
        support=support,
        missing_information=(
            "a registered RES-69 classical LoA calculator and coverage authority",
        ),
        safe_descriptions=(
            "simple B-minus-A bias and SD difference remain the only BA V1 numerical outputs",
            "coverage and interchangeability interpretations are not authorized",
        ),
    )


def refuse_bland_altman_interpretation(
    support: StatisticalSupport | None = None,
    *,
    claim: str = "claim acceptable agreement, 95% coverage, or interchangeability",
) -> RefusalResult:
    """Block BA interpretation claims outside the narrow V1 output boundary."""

    return refusal(
        claim,
        RES69ReasonCode.INTERPRETATION_NOT_AUTHORIZED,
        support=support,
        missing_information=(
            "a separately registered agreement/coverage interpretation authority",
        ),
        safe_descriptions=(
            "the descriptive BA bias and SD difference may be reported without an "
            "acceptability claim",
        ),
    )


# Readable aliases used by callers and the decision record.
calculate_simple_bland_altman = calculate_bland_altman_summary
request_ba_limits = request_classical_bland_altman_limits
calculate_classical_bland_altman_limits = request_classical_bland_altman_limits


__all__ = [
    "build_method_comparison_design_authority",
    "build_method_comparison_design_evidence",
    "calculate_bland_altman_summary",
    "calculate_classical_bland_altman_limits",
    "calculate_simple_bland_altman",
    "refuse_bland_altman_interpretation",
    "request_ba_limits",
    "request_classical_bland_altman_limits",
]
