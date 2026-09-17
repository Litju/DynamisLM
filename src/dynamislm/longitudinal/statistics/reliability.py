"""Source-bound reliability and repeatability calculations for RES-69."""

from __future__ import annotations

import math
from dataclasses import replace

from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
)
from dynamislm.longitudinal.statistics.models import (
    AuthorityStatus,
    MissingnessPolicy,
    ReliabilityDesignAuthority,
    ReliabilityDesignEvidence,
    ReliabilityErrorScale,
    ReliabilityQuestion,
    ReliabilityReplicatePair,
    RES69ReasonCode,
    StableUnderlyingQuantityStatus,
    StatisticalObservationReference,
    StatisticalResult,
    StatisticalSourceRecordReference,
    StatisticalSupport,
    SystematicTrialEffectAssessment,
)
from dynamislm.longitudinal.statistics.registry import (
    GENERIC_SEM,
    MDC_SDC,
    RES69_DIMENSIONLESS_UNIT,
    RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
    RES69_LOG_RATIO_UNIT,
    RES69_LOG_SCALE_ERROR_OPERATION,
    RES69_LOG_TYPICAL_ERROR_ESTIMAND,
    RES69_LOWER_FACTOR_ESTIMAND,
    RES69_LOWER_PERCENT_ESTIMAND,
    RES69_MEAN_LOG_SHIFT_ESTIMAND,
    RES69_MEAN_TRIAL_SHIFT_ESTIMAND,
    RES69_MULTIPLICATIVE_FACTOR_ESTIMAND,
    RES69_PERCENT_UNIT,
    RES69_RANDOM_ERROR_SD_ESTIMAND,
    RES69_RAW_REFERENCE_MEAN_ESTIMAND,
    RES69_RAW_RELATIVE_ERROR_OPERATION,
    RES69_RAW_RELATIVE_ERROR_PERCENT_ESTIMAND,
    RES69_REGISTRY_VERSION,
    RES69_REPLICATE_ORDERING,
    RES69_SCALE_REGISTRY,
    RES69_SD_DIFFERENCE_ESTIMAND,
    RES69_SD_LOG_DIFFERENCE_ESTIMAND,
    RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION,
    RES69_UPPER_FACTOR_ESTIMAND,
    RES69_UPPER_PERCENT_ESTIMAND,
    SEM_FROM_REGISTERED_ICC,
    TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1,
    TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
    MeasurementScaleRegistry,
)
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    exact_common_unit,
    measurement_target_signature,
    scalar_value,
    validate_statistical_support,
)
from dynamislm.longitudinal.statistics.validation import (
    make_estimate,
    make_result,
    refusal,
    refusal_for_exception,
    resolve_scale_semantics,
    validate_reliability_authority,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
)
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import RefusalResult
from dynamislm.serialization import canonical_hash

_NOT_SUPPLIED = object()


def _parameters(*items: tuple[str, str | int | float]) -> tuple[MetadataEntry, ...]:
    return tuple(MetadataEntry(key, value) for key, value in items)


def _source_evidence_references(
    authority: ReliabilityDesignAuthority,
) -> tuple[EvidenceReference, ...]:
    return authority.evidence_references


def build_reliability_design_evidence(
    *,
    support: StatisticalSupport,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    study_identity: RegistryReference,
    replicate_pairs: tuple[ReliabilityReplicatePair, ...],
    target_measurement_identity_ids: tuple[ScientificIdentifier, ...],
    target_construct: RegistryReference,
    target_test_family: RegistryReference,
    target_measurand: RegistryReference,
    target_metric_definition: RegistryReference,
    target_unit: UnitReference,
    protocol_reference: RegistryReference,
    evidence_references: tuple[EvidenceReference, ...],
    repeatability_question: ReliabilityQuestion,
    stable_underlying_quantity: StableUnderlyingQuantityStatus,
    systematic_trial_effect: SystematicTrialEffectAssessment,
    error_scale: ReliabilityErrorScale,
    missingness_policy: MissingnessPolicy,
    balanced_design: bool,
    producing_method: RegistryReference,
    method_identity: RegistryReference | None = None,
    device_identity: RegistryReference | None = None,
    rater_identity: RegistryReference | None = None,
    design_identity: RegistryReference | None = None,
    replicate_ordering: RegistryReference = RES69_REPLICATE_ORDERING,
    registry_version: str = RES69_REGISTRY_VERSION,
) -> ReliabilityDesignEvidence:
    """Create a typed evidence record; authority is minted only by its builder."""

    if not isinstance(systematic_trial_effect, SystematicTrialEffectAssessment):
        raise ValueError("systematic_trial_effect must be a SystematicTrialEffectAssessment")
    if not isinstance(missingness_policy, MissingnessPolicy):
        raise ValueError("missingness_policy must be a MissingnessPolicy")
    return ReliabilityDesignEvidence(
        support=support,
        source_records=source_records,
        study_identity=study_identity,
        replicate_pairs=replicate_pairs,
        replicate_ordering=replicate_ordering,
        target_measurement_identity_ids=target_measurement_identity_ids,
        target_construct=target_construct,
        target_test_family=target_test_family,
        target_measurand=target_measurand,
        target_metric_definition=target_metric_definition,
        target_unit=target_unit,
        protocol_reference=protocol_reference,
        method_identity=method_identity,
        device_identity=device_identity,
        rater_identity=rater_identity,
        evidence_references=evidence_references,
        repeatability_question=repeatability_question,
        stable_underlying_quantity=stable_underlying_quantity,
        systematic_trial_effect=systematic_trial_effect,
        error_scale=error_scale,
        missingness_policy=missingness_policy,
        balanced_design=balanced_design,
        producing_method=producing_method,
        registry_version=registry_version,
        design_identity=design_identity,
    )


def _validate_reliability_evidence(evidence: ReliabilityDesignEvidence) -> None:
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
            "reliability source records do not match support record references",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    entry_by_id = {entry.canonical_entry_id: entry for entry in support.included_entries}
    if not evidence.replicate_pairs:
        raise StatisticalConstraintError(
            "reliability authority requires exact replicate pairs",
            RES69ReasonCode.INCOMPLETE_PAIR.value,
        )
    pair_entry_ids: list[InstanceIdentifier] = []
    pair_athletes: list[InstanceIdentifier] = []
    identity_ids: set[ScientificIdentifier] = set()
    for pair in evidence.replicate_pairs:
        first = entry_by_id.get(pair.first_entry_id)
        second = entry_by_id.get(pair.second_entry_id)
        if first is None or second is None:
            raise StatisticalConstraintError(
                "reliability pair references an entry outside exact support",
                RES69ReasonCode.INCOMPLETE_PAIR.value,
            )
        if (
            StatisticalObservationReference.from_entry(first) != pair.first
            or StatisticalObservationReference.from_entry(second) != pair.second
        ):
            raise StatisticalConstraintError(
                "reliability pair observation or entry hash does not match support",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        pair_entry_ids.extend((pair.first_entry_id, pair.second_entry_id))
        pair_athletes.append(pair.athlete_id)
        identity_ids.update(
            (first.observation.identity.identity_id, second.observation.identity.identity_id)
        )
        if pair.first.athlete_id != pair.second.athlete_id:
            raise StatisticalConstraintError(
                "reliability pair has mismatched athlete identities",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
    if len(set(pair_entry_ids)) != len(pair_entry_ids) or set(pair_entry_ids) != {
        entry.canonical_entry_id for entry in support.included_entries
    }:
        raise StatisticalConstraintError(
            "reliability support must contain exactly the paired observations",
            RES69ReasonCode.INCOMPLETE_PAIR.value,
        )
    if len(set(pair_athletes)) != len(pair_athletes):
        raise StatisticalConstraintError(
            "V1 reliability requires one exact pair per independent subject",
            RES69ReasonCode.UNBALANCED_RELIABILITY_SUPPORT.value,
        )
    if set(evidence.target_measurement_identity_ids) != identity_ids:
        raise StatisticalConstraintError(
            "target measurement identity IDs do not match paired observations",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if any(
        measurement_target_signature(entry)
        != measurement_target_signature(support.included_entries[0])
        for entry in support.included_entries[1:]
    ):
        raise StatisticalConstraintError(
            "reliability observations do not share one target construct/measurand/metric",
            RES69ReasonCode.IDENTITY_UNRESOLVED.value,
        )
    target = support.included_entries[0].observation.identity.semantic
    if (
        target.construct.stable_id != evidence.target_construct.stable_id
        or target.test_family.stable_id != evidence.target_test_family.stable_id
        or target.measurand.stable_id != evidence.target_measurand.stable_id
        or target.metric_definition.stable_id != evidence.target_metric_definition.stable_id
    ):
        raise StatisticalConstraintError(
            "reliability target semantic references do not match observations",
            RES69ReasonCode.IDENTITY_UNRESOLVED.value,
        )
    for entry in support.included_entries:
        identity = entry.observation.identity
        if evidence.method_identity is not None:
            actual_method = (
                identity.processing.registered_operation or identity.version.processing_method
            )
            if actual_method.stable_id != evidence.method_identity.stable_id:
                raise StatisticalConstraintError(
                    "reliability method identity does not match source observations",
                    RES69ReasonCode.SUPPORT_MISMATCH.value,
                )
        if evidence.device_identity is not None:
            if (
                identity.acquisition.device is None
                or identity.acquisition.device.stable_id != evidence.device_identity.stable_id
            ):
                raise StatisticalConstraintError(
                    "reliability device identity does not match source observations",
                    RES69ReasonCode.SUPPORT_MISMATCH.value,
                )
    unit = exact_common_unit(support.included_entries)
    if unit != evidence.target_unit:
        raise StatisticalConstraintError(
            "reliability target unit does not match exact source unit",
            RES69ReasonCode.UNIT_MISMATCH.value,
        )
    if support.missingness_policy != evidence.missingness_policy:
        raise StatisticalConstraintError(
            "reliability evidence missingness policy does not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if evidence.replicate_ordering != RES69_REPLICATE_ORDERING:
        raise StatisticalConstraintError(
            "replicate ordering is not the registered trial-one then trial-two ordering",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    protocol = target.protocol
    if protocol is None or protocol.stable_id != evidence.protocol_reference.stable_id:
        raise StatisticalConstraintError(
            "reliability protocol evidence does not match the target identity",
            RES69ReasonCode.IDENTITY_UNRESOLVED.value,
        )
    if evidence.balanced_design:
        counts: dict[InstanceIdentifier, int] = {}
        for entry in support.included_entries:
            athlete_id = entry.observation.context.athlete_id
            counts[athlete_id] = counts.get(athlete_id, 0) + 1
        if any(count != 2 for count in counts.values()):
            raise StatisticalConstraintError(
                "balanced reliability authority requires exactly two observations per subject",
                RES69ReasonCode.UNBALANCED_RELIABILITY_SUPPORT.value,
            )


def build_reliability_design_authority(
    evidence: ReliabilityDesignEvidence,
) -> ReliabilityDesignAuthority:
    """Normalize source/protocol evidence into a source-bound authority object."""

    if not isinstance(evidence, ReliabilityDesignEvidence):
        raise ValueError("evidence must be a ReliabilityDesignEvidence")
    _validate_reliability_evidence(evidence)
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
    authority = ReliabilityDesignAuthority(
        support_id=support.canonical_support_id,
        support_hash=support.canonical_support_hash,
        analysis_input_ids=support.input_ids,
        analysis_input_hashes=support.input_hashes,
        source_records=source_records,
        source_artifacts=support.source_artifacts,
        source_provenance=support.source_provenance,
        study_identity=evidence.study_identity,
        replicate_pairs=tuple(
            sorted(evidence.replicate_pairs, key=lambda item: item.pair_id.qualified)
        ),
        replicate_ordering=evidence.replicate_ordering,
        target_measurement_identity_ids=tuple(
            sorted(evidence.target_measurement_identity_ids, key=lambda item: item.stable_id)
        ),
        target_construct=evidence.target_construct,
        target_test_family=evidence.target_test_family,
        target_measurand=evidence.target_measurand,
        target_metric_definition=evidence.target_metric_definition,
        target_unit=evidence.target_unit,
        protocol_reference=evidence.protocol_reference,
        method_identity=evidence.method_identity,
        device_identity=evidence.device_identity,
        rater_identity=evidence.rater_identity,
        evidence_references=evidence.evidence_references,
        repeatability_question=evidence.repeatability_question,
        stable_underlying_quantity=evidence.stable_underlying_quantity,
        systematic_trial_effect=evidence.systematic_trial_effect,
        error_scale=evidence.error_scale,
        missingness_policy=evidence.missingness_policy,
        balanced_design=evidence.balanced_design,
        producing_method=evidence.producing_method,
        registry_version=evidence.registry_version,
        source_evidence_hash=canonical_hash(evidence),
        authority_status=AuthorityStatus.UNVERIFIED,
        design_identity=evidence.design_identity or evidence.study_identity,
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


def _validated_pairs(
    support: StatisticalSupport,
    authority: ReliabilityDesignAuthority,
) -> tuple[
    tuple[
        ReliabilityReplicatePair,
        LongitudinalObservationEntry,
        LongitudinalObservationEntry,
        float,
        float,
    ],
    ...,
]:
    validate_reliability_authority(authority, support)
    validate_statistical_support(support)
    if (
        authority.analysis_input_ids != support.input_ids
        or authority.analysis_input_hashes != support.input_hashes
    ):
        raise StatisticalConstraintError(
            "reliability authority analysis-input lineage does not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if authority.source_records != support.source_records:
        raise StatisticalConstraintError(
            "reliability authority source records do not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if (
        authority.source_artifacts != support.source_artifacts
        or authority.source_provenance != support.source_provenance
    ):
        raise StatisticalConstraintError(
            "reliability authority provenance does not match support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if authority.replicate_ordering != RES69_REPLICATE_ORDERING:
        raise StatisticalConstraintError(
            "reliability replicate ordering is not registered",
            RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        )
    entries = {entry.canonical_entry_id: entry for entry in support.included_entries}
    paired_ids: set[InstanceIdentifier] = set()
    paired_athletes: set[InstanceIdentifier] = set()
    values = []
    validated = []
    for pair in authority.replicate_pairs:
        first = entries.get(pair.first_entry_id)
        second = entries.get(pair.second_entry_id)
        if first is None or second is None:
            raise StatisticalConstraintError(
                "reliability support has an incomplete exact pair",
                RES69ReasonCode.INCOMPLETE_PAIR.value,
            )
        if (
            StatisticalObservationReference.from_entry(first) != pair.first
            or StatisticalObservationReference.from_entry(second) != pair.second
        ):
            raise StatisticalConstraintError(
                "reliability pair hash does not match support",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        if pair.athlete_id in paired_athletes:
            raise StatisticalConstraintError(
                "reliability support repeats an independent subject",
                RES69ReasonCode.UNBALANCED_RELIABILITY_SUPPORT.value,
            )
        first_value, first_unit = scalar_value(first)
        second_value, second_unit = scalar_value(second)
        if first_unit != second_unit or first_unit != authority.target_unit:
            raise StatisticalConstraintError(
                "reliability arithmetic requires one exact common source unit",
                RES69ReasonCode.UNIT_MISMATCH.value,
            )
        difference = second_value - first_value
        paired_ids.update((pair.first_entry_id, pair.second_entry_id))
        paired_athletes.add(pair.athlete_id)
        values.append(difference)
        validated.append((pair, first, second, first_value, second_value))
    if paired_ids != {entry.canonical_entry_id for entry in support.included_entries}:
        raise StatisticalConstraintError(
            "reliability support contains an unpaired or missing observation",
            RES69ReasonCode.INCOMPLETE_PAIR.value,
        )
    if len(validated) < 2:
        raise StatisticalConstraintError(
            "two-replicate random-error SD requires N >= 2 complete subject pairs",
            RES69ReasonCode.DATA_ADEQUACY_INSUFFICIENT.value,
        )
    if not authority.balanced_design:
        raise StatisticalConstraintError(
            "V1 two-replicate reliability requires a balanced design",
            RES69ReasonCode.UNBALANCED_RELIABILITY_SUPPORT.value,
        )
    if authority.stable_underlying_quantity is not StableUnderlyingQuantityStatus.SUPPORTED:
        raise StatisticalConstraintError(
            "stable-underlying-quantity assessment is not supported by source authority",
            RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
        )
    return tuple(validated)


def _sample_sd(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        raise ValueError("sample SD requires at least two values")
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _reliability_authority_references(
    authority: ReliabilityDesignAuthority,
) -> tuple[RegistryReference, ...]:
    return (authority.design_or_study_identity, authority.producing_method)


def calculate_two_replicate_random_error(
    support: StatisticalSupport,
    authority: object,
) -> StatisticalResult | RefusalResult:
    """Calculate mean trial shift, SD difference, and SD difference/sqrt(2)."""

    claim = "calculate two-replicate within-subject random error SD"
    try:
        if not isinstance(authority, ReliabilityDesignAuthority):
            raise StatisticalConstraintError(
                "source-bound ReliabilityDesignAuthority is required",
                RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
            )
        if authority.error_scale is ReliabilityErrorScale.LOG_MULTIPLICATIVE:
            raise StatisticalConstraintError(
                "log-multiplicative designs require the registered log-scale estimator",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        pairs = _validated_pairs(support, authority)
        differences = tuple(item[4] - item[3] for item in pairs)
        mean_shift = math.fsum(differences) / len(differences)
        sd_difference = _sample_sd(differences)
        random_error_sd = sd_difference / math.sqrt(2.0)
        parameters = _parameters(
            ("pair_count", len(pairs)),
            ("support_hash", support.canonical_support_hash),
            ("authority_hash", authority.canonical_authority_hash),
            ("estimator_identity", TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1.stable_id),
        )
        estimates = (
            make_estimate(
                estimand=RES69_MEAN_TRIAL_SHIFT_ESTIMAND,
                value=mean_shift,
                unit=authority.target_unit,
                estimator=TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_SD_DIFFERENCE_ESTIMAND,
                value=sd_difference,
                unit=authority.target_unit,
                estimator=TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_RANDOM_ERROR_SD_ESTIMAND,
                value=random_error_sd,
                unit=authority.target_unit,
                estimator=TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
                parameters=parameters,
            ),
        )
        return make_result(
            support,
            operation=RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION,
            estimator=TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
            estimates=estimates,
            parameters=parameters,
            authority_references=_reliability_authority_references(authority),
            authority_hashes=(authority.canonical_authority_hash,),
            evidence_references=_source_evidence_references(authority),
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


# Typical error and within-subject SD are aliases under the one registered
# two-replicate estimator; they are intentionally not separate calculations.
calculate_typical_error = calculate_two_replicate_random_error


def calculate_raw_relative_error_percent(
    support: StatisticalSupport,
    authority: object,
    *,
    registry: MeasurementScaleRegistry = RES69_SCALE_REGISTRY,
    denominator: object = _NOT_SUPPLIED,
) -> StatisticalResult | RefusalResult:
    """Calculate raw relative error using the derived pooled 2N raw grand mean."""

    claim = "calculate two-replicate pooled raw relative error percent"
    try:
        if denominator is not _NOT_SUPPLIED:
            raise StatisticalConstraintError(
                "raw relative error denominator is derived and cannot be caller supplied",
                RES69ReasonCode.SUPPORT_MISMATCH.value,
            )
        if not isinstance(authority, ReliabilityDesignAuthority):
            raise StatisticalConstraintError(
                "source-bound ReliabilityDesignAuthority is required",
                RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
            )
        if authority.error_scale is not ReliabilityErrorScale.RAW_RELATIVE:
            raise StatisticalConstraintError(
                "raw relative error requires RAW_RELATIVE source/protocol authority",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        pairs = _validated_pairs(support, authority)
        semantics, key, unit = resolve_scale_semantics(support, registry=registry)
        if not semantics.raw_relative_error_authorized:
            raise StatisticalConstraintError(
                "registered scale semantics do not authorize raw relative error",
                RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
            )
        raw_values = tuple(value for pair in pairs for value in (pair[3], pair[4]))
        raw_reference_mean = math.fsum(raw_values) / len(raw_values)
        if raw_reference_mean <= 0:
            raise StatisticalConstraintError(
                "pooled raw grand mean must be strictly positive",
                RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
            )
        differences = tuple(item[4] - item[3] for item in pairs)
        random_error_sd = _sample_sd(differences) / math.sqrt(2.0)
        relative_error_percent = 100.0 * random_error_sd / raw_reference_mean
        parameters = _parameters(
            ("pair_count", len(pairs)),
            ("support_hash", support.canonical_support_hash),
            ("authority_hash", authority.canonical_authority_hash),
            ("denominator_identity", TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1.stable_id),
        )
        estimates = (
            make_estimate(
                estimand=RES69_RAW_REFERENCE_MEAN_ESTIMAND,
                value=raw_reference_mean,
                unit=unit,
                estimator=TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_RANDOM_ERROR_SD_ESTIMAND,
                value=random_error_sd,
                unit=unit,
                estimator=TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_RAW_RELATIVE_ERROR_PERCENT_ESTIMAND,
                value=relative_error_percent,
                unit=RES69_PERCENT_UNIT,
                estimator=TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1,
                parameters=parameters,
            ),
        )
        return make_result(
            support,
            operation=RES69_RAW_RELATIVE_ERROR_OPERATION,
            estimator=TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1,
            estimates=estimates,
            parameters=parameters,
            authority_references=(
                *_reliability_authority_references(authority),
                semantics.authority_reference,
            ),
            authority_hashes=(authority.canonical_authority_hash,),
            evidence_references=(
                *_source_evidence_references(authority),
                *semantics.evidence_references,
            ),
            scale_semantic_key=key,
            scale_semantics_authority=semantics.authority_reference,
            scale_semantics_hash=canonical_hash(semantics),
            registry_version=registry.registry_version,
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


def calculate_log_scale_typical_error(
    support: StatisticalSupport,
    authority: object,
    *,
    registry: MeasurementScaleRegistry = RES69_SCALE_REGISTRY,
) -> StatisticalResult | RefusalResult:
    """Calculate log typical error and its asymmetric multiplicative interval."""

    claim = "calculate log-scale multiplicative typical error"
    try:
        if not isinstance(authority, ReliabilityDesignAuthority):
            raise StatisticalConstraintError(
                "source-bound ReliabilityDesignAuthority is required",
                RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
            )
        if authority.error_scale is not ReliabilityErrorScale.LOG_MULTIPLICATIVE:
            raise StatisticalConstraintError(
                "log typical error requires LOG_MULTIPLICATIVE source/protocol authority",
                RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
            )
        pairs = _validated_pairs(support, authority)
        semantics, key, _unit = resolve_scale_semantics(support, registry=registry)
        if not semantics.log_error_authorized:
            raise StatisticalConstraintError(
                "registered scale semantics do not authorize log-scale error",
                RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
            )
        log_differences = []
        for pair in pairs:
            if pair[3] <= 0 or pair[4] <= 0:
                raise StatisticalConstraintError(
                    "log typical error requires strictly positive replicate values",
                    RES69ReasonCode.NONPOSITIVE_LOG_INPUT.value,
                )
            log_differences.append(math.log(pair[4]) - math.log(pair[3]))
        logs = tuple(log_differences)
        mean_log_shift = math.fsum(logs) / len(logs)
        sd_log_difference = _sample_sd(logs)
        te_log = sd_log_difference / math.sqrt(2.0)
        factor = math.exp(te_log)
        lower_factor = math.exp(-te_log)
        upper_factor = math.exp(te_log)
        lower_percent = 100.0 * (1.0 - lower_factor)
        upper_percent = 100.0 * (upper_factor - 1.0)
        parameters = _parameters(
            ("pair_count", len(pairs)),
            ("support_hash", support.canonical_support_hash),
            ("authority_hash", authority.canonical_authority_hash),
            ("canonical_factor_interval", f"[{lower_factor!r},{upper_factor!r}]"),
        )
        estimates = (
            make_estimate(
                estimand=RES69_MEAN_LOG_SHIFT_ESTIMAND,
                value=mean_log_shift,
                unit=RES69_LOG_RATIO_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_SD_LOG_DIFFERENCE_ESTIMAND,
                value=sd_log_difference,
                unit=RES69_LOG_RATIO_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_LOG_TYPICAL_ERROR_ESTIMAND,
                value=te_log,
                unit=RES69_LOG_RATIO_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_MULTIPLICATIVE_FACTOR_ESTIMAND,
                value=factor,
                unit=RES69_DIMENSIONLESS_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_LOWER_FACTOR_ESTIMAND,
                value=lower_factor,
                unit=RES69_DIMENSIONLESS_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_UPPER_FACTOR_ESTIMAND,
                value=upper_factor,
                unit=RES69_DIMENSIONLESS_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_LOWER_PERCENT_ESTIMAND,
                value=lower_percent,
                unit=RES69_PERCENT_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_UPPER_PERCENT_ESTIMAND,
                value=upper_percent,
                unit=RES69_PERCENT_UNIT,
                estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
                parameters=parameters,
            ),
        )
        return make_result(
            support,
            operation=RES69_LOG_SCALE_ERROR_OPERATION,
            estimator=RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
            estimates=estimates,
            parameters=parameters,
            authority_references=(
                *_reliability_authority_references(authority),
                semantics.authority_reference,
            ),
            authority_hashes=(authority.canonical_authority_hash,),
            evidence_references=(
                *_source_evidence_references(authority),
                *semantics.evidence_references,
            ),
            scale_semantic_key=key,
            scale_semantics_authority=semantics.authority_reference,
            scale_semantics_hash=canonical_hash(semantics),
            registry_version=registry.registry_version,
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


def refuse_unimplemented_reliability_operation(
    operation: RegistryReference,
    *,
    support: StatisticalSupport | None = None,
) -> RefusalResult:
    """Represent deferred/rejected reliability methods without placeholder arithmetic."""

    return refusal(
        f"calculate {operation.display_label}",
        RES69ReasonCode.OPERATION_NOT_REGISTERED,
        support=support,
        missing_information=("a registered RES-69 deterministic calculator for this operation",),
    )


def calculate_sem_from_icc(
    support: StatisticalSupport | None = None,
) -> RefusalResult:
    return refuse_unimplemented_reliability_operation(SEM_FROM_REGISTERED_ICC, support=support)


def calculate_generic_sem(
    support: StatisticalSupport | None = None,
) -> RefusalResult:
    return refuse_unimplemented_reliability_operation(GENERIC_SEM, support=support)


def calculate_mdc_sdc(
    support: StatisticalSupport | None = None,
) -> RefusalResult:
    return refuse_unimplemented_reliability_operation(MDC_SDC, support=support)


calculate_raw_relative_error = calculate_raw_relative_error_percent
calculate_log_typical_error = calculate_log_scale_typical_error


__all__ = [
    "build_reliability_design_authority",
    "build_reliability_design_evidence",
    "calculate_generic_sem",
    "calculate_log_scale_typical_error",
    "calculate_log_typical_error",
    "calculate_mdc_sdc",
    "calculate_raw_relative_error",
    "calculate_raw_relative_error_percent",
    "calculate_sem_from_icc",
    "calculate_two_replicate_random_error",
    "calculate_typical_error",
    "refuse_unimplemented_reliability_operation",
]
