"""RES-67 numerical gold fixtures and adversarial scientific-boundary tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from inspect import signature
from typing import Any

import pytest

from dynamislm.comparability.models import ComparabilityState
from dynamislm.measurement.field_testing._common import (
    build_field_test_qualification_source_observation,
    build_source_qualification_observation,
    normalize_field_test_qualification,
)
from dynamislm.measurement.field_testing.cod import (
    CODDeficitResult,
    Standard505Result,
    Standard505TrialObservation,
    aggregate_standard_505_trials,
    build_standard_505_trial_observation,
    calculate_cod_deficit,
    qualify_standard_505_trial,
    refuse_505_asymmetry,
    standard_505_protocol_v1,
)
from dynamislm.measurement.field_testing.comparability import (
    compare_maximum_sprint_velocity,
    compare_rsa_results,
)
from dynamislm.measurement.field_testing.identity import (
    FieldTestArtifactHashScope,
    FieldTestArtifactStatus,
    FieldTestFamily,
    FieldTestHashAlgorithm,
    FieldTestingAcquisitionRecord,
    FieldTestingProtocolIdentity,
    FieldTestingSegmentDefinition,
    FieldTestingSourceArtifact,
    FieldTestingSupport,
    FieldTestingTimebase,
    FieldTestQualificationStatus,
    FieldTestSensorModality,
    FieldTestTimebaseKind,
    ReactionTimeSemantics,
    StartInitiationMode,
    TimingGateTopology,
)
from dynamislm.measurement.field_testing.ift import (
    IFTStageCompletion,
    IFTTerminationReason,
    IFTTestEvidence,
    VIFTResult,
    build_ift_stage_completion_source_observation,
    build_ift_stage_evidence,
    build_ift_stage_source_observation,
    build_ift_termination_evidence,
    build_ift_termination_source_observation,
    build_ift_test_evidence,
    calculate_vift,
    ift30_15_protocol_v1,
    qualify_ift_stage,
    refuse_vift_as_mas,
    refuse_vift_as_mss,
    refuse_vift_as_vo2max,
)
from dynamislm.measurement.field_testing.registry import (
    IFT30_15_PROTOCOL_V1,
    LINEAR_SPRINT_30M_PROTOCOL_V1,
    METER_PER_SECOND,
    RSA_CONSTRUCT,
    RSA_PERCENT_DECREMENT_MEASURAND,
    RSA_TEST_FAMILY,
    SECOND,
    SHORT_LINEAR_SPRINT_CONSTRUCT,
    SHORT_LINEAR_SPRINT_TEST_FAMILY,
    SPLIT_TIME_MEASURAND,
)
from dynamislm.measurement.field_testing.rsa import (
    RSACriterionSprintEvidence,
    RSAMovementMode,
    RSAProtocolIdentity,
    RSARecoveryMode,
    RSARepetitionObservation,
    RSAResult,
    build_rsa_criterion_sprint_evidence,
    build_rsa_criterion_sprint_source_observation,
    build_rsa_repetition_observation,
    calculate_rsa_best_time,
    calculate_rsa_mean_time,
    calculate_rsa_percent_decrement,
    calculate_rsa_total_time,
    qualify_rsa_repetition,
    refuse_alternate_rsa_decrement,
    refuse_rsa_decrement_as_fatigue,
    rsa_6x40m_shuttle_protocol_v1,
)
from dynamislm.measurement.field_testing.sprint import (
    MaximumSprintVelocityResult,
    SegmentAverageVelocityResult,
    SprintSplitKind,
    SprintTimeObservation,
    SprintVelocitySample,
    SprintVelocitySeries,
    SprintVelocitySeriesEvidence,
    aggregate_linear_sprint_30m_reference,
    build_sprint_time_observation,
    build_velocity_series_evidence,
    cumulative_split,
    derive_interval_split,
    derive_segment_average_velocity,
    interval_split,
    linear_sprint_30m_protocol_v1,
    refuse_sampled_maximum_as_sustained_maximum,
    refuse_segment_average_velocity_as_max_speed,
    refuse_sprint_acceleration,
    sampled_maximum_velocity,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    SamplingCharacteristics,
    ScientificIdentifier,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import CategoricalValue
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _replace_any(value: Any, **changes: Any) -> Any:
    return replace(value, **changes)


def _ref(object_type: str, key: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("fixture", object_type, key, "1"), key)


def _context(
    name: str,
    *,
    test_instance: str,
    trial: str | None,
    athlete: str = "athlete-1",
) -> ObservationContext:
    return ObservationContext(
        context_id=InstanceIdentifier("context", name),
        athlete_id=InstanceIdentifier("athlete", athlete),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", test_instance),
        trial_id=None if trial is None else InstanceIdentifier("trial", trial),
        observed_at=OBSERVED_AT,
        population_context="SYNTHETIC_TRAINED_TEAM_SPORT_ADULT",
    )


def _artifact(name: str, digest: str | None = None) -> FieldTestingSourceArtifact:
    return FieldTestingSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", name),
        content_digest=digest or f"sha256:synthetic-{name}",
        media_type="application/vnd.synthetic.field-test",
        immutable=True,
        hash_algorithm=FieldTestHashAlgorithm.SHA256,
        hash_scope=FieldTestArtifactHashScope.CONTENT_BYTES,
        status=FieldTestArtifactStatus.VERIFIED,
    )


def _acquisition(
    name: str,
    *,
    device: str = "timing-gate-1",
    modality: FieldTestSensorModality = FieldTestSensorModality.TIMING_GATE,
) -> FieldTestingAcquisitionRecord:
    return FieldTestingAcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", name),
        device=_ref("device", device),
        source_artifact_id=InstanceIdentifier("artifact", name),
        provider="synthetic-provider",
        sensor_modality=modality,
    )


def _qualification_observation(
    target_observation: ScientificMeasurementObservation,
    *,
    status: FieldTestQualificationStatus = FieldTestQualificationStatus.QUALIFIED,
) -> ScientificMeasurementObservation:
    artifact_id = target_observation.provenance.source_artifacts[0].artifact_id
    acquisition_id = target_observation.provenance.acquisitions[0].acquisition_id
    source_artifact = next(
        artifact
        for artifact in target_observation.provenance.source_artifacts
        if artifact.artifact_id == artifact_id
    )
    acquisition = next(
        item
        for item in target_observation.provenance.acquisitions
        if item.acquisition_id == acquisition_id
    )
    assert isinstance(source_artifact, FieldTestingSourceArtifact)
    assert isinstance(acquisition, FieldTestingAcquisitionRecord)
    source_observation = build_field_test_qualification_source_observation(
        target_observation=target_observation,
        reported_status=status,
        source_artifact=source_artifact,
        acquisition=acquisition,
    )
    return source_observation


def _qualified_sprint_trial(
    name: str,
    *,
    protocol: FieldTestingProtocolIdentity,
    time_seconds: float,
    end_m: float = 10.0,
    test_instance: str = "linear",
    trial_id: str | None = None,
    athlete: str = "athlete-1",
) -> SprintTimeObservation:
    artifact = _artifact(name)
    acquisition = _acquisition(name)
    source = build_sprint_time_observation(
        observation_id=InstanceIdentifier("observation", name),
        context=_context(
            f"context-{name}",
            test_instance=test_instance,
            trial=name if trial_id is None else trial_id,
            athlete=athlete,
        ),
        protocol=protocol,
        split=cumulative_split(end_m),
        time_seconds=time_seconds,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    qualification_observation = _qualification_observation(source.observation)
    qualification = normalize_field_test_qualification(
        qualification_observation,
        source.observation,
    )
    return SprintTimeObservation(source.observation, source.split, qualification)


def test_sprint_split_and_segment_velocity_gold_fixture() -> None:
    protocol = linear_sprint_30m_protocol_v1()
    start = _qualified_sprint_trial(
        "sprint-5", protocol=protocol, time_seconds=1.0, end_m=5.0, trial_id="same-trial"
    )
    end = _qualified_sprint_trial(
        "sprint-10", protocol=protocol, time_seconds=1.8, trial_id="same-trial"
    )

    interval = derive_interval_split(start, end)
    assert isinstance(interval, SprintTimeObservation)
    assert interval.split.kind is SprintSplitKind.INTERVAL
    assert interval.source_time_seconds == pytest.approx(0.8)

    velocity = derive_segment_average_velocity(
        interval,
        FieldTestingSegmentDefinition("5-10m", 5.0, 10.0),
    )
    assert isinstance(velocity, SegmentAverageVelocityResult)
    assert velocity.value == pytest.approx(6.25)
    assert velocity.observation.result.unit == METER_PER_SECOND
    assert refuse_segment_average_velocity_as_max_speed().blocks_claim
    assert refuse_sprint_acceleration().blocks_claim


def test_sprint_identity_attacks_and_incompatible_clock_refuse() -> None:
    protocol = linear_sprint_30m_protocol_v1()
    start = _qualified_sprint_trial(
        "attack-5", protocol=protocol, time_seconds=1.0, end_m=5.0, trial_id="same-trial"
    )
    end = _qualified_sprint_trial(
        "attack-10", protocol=protocol, time_seconds=1.8, trial_id="same-trial"
    )
    with pytest.raises(ValueError):
        replace(start, split=interval_split(0.0, 5.0))
    with pytest.raises(ValueError):
        replace(end, split=cumulative_split(0.0))

    changed_protocol = replace(protocol, start_line_offset_m=0.50)
    changed_end = _qualified_sprint_trial(
        "attack-changed-start",
        protocol=changed_protocol,
        time_seconds=1.8,
        trial_id="same-trial",
    )
    refused = derive_interval_split(start, changed_end)
    assert not isinstance(refused, SprintTimeObservation)
    assert refused.blocks_claim

    timed_protocol = replace(
        protocol,
        timebase=FieldTestingTimebase(
            kind=FieldTestTimebaseKind.EXPLICIT,
            times_s=(0.0, 0.01),
        ),
    )
    changed_clock = _qualified_sprint_trial(
        "attack-changed-clock",
        protocol=timed_protocol,
        time_seconds=1.8,
        trial_id="same-trial",
    )
    refused_clock = derive_interval_split(start, changed_clock)
    assert not isinstance(refused_clock, SprintTimeObservation)

    with pytest.raises(ValueError):
        SprintTimeObservation(0.8, interval_split(5.0, 10.0))  # type: ignore[arg-type]


def _velocity_evidence(
    name: str,
    *,
    device: str = "radar-1",
    modality: FieldTestSensorModality = FieldTestSensorModality.RADAR,
    samples: tuple[tuple[float, float], ...] = ((0.0, 3.0), (0.1, 5.0), (0.2, 7.2), (0.3, 6.0)),
) -> tuple[MaximumSprintVelocityResult, SprintVelocitySeries]:
    protocol = FieldTestingProtocolIdentity(
        family=FieldTestFamily.MAXIMUM_SPRINT_VELOCITY,
        protocol_version="1.0.0",
        reference=_ref("protocol", "maximum-sprint-velocity-fixture"),
    )
    timebase = FieldTestingTimebase(
        kind=FieldTestTimebaseKind.EXPLICIT,
        times_s=tuple(item[0] for item in samples),
    )
    support = FieldTestingSupport(
        support_id=InstanceIdentifier("support", name),
        start_index=0,
        end_index=len(samples) - 1,
        start_time_s=samples[0][0],
        end_time_s=samples[-1][0],
    )
    series = SprintVelocitySeries(
        source_artifact_id=InstanceIdentifier("artifact", name),
        source_measurement_identity_id=ScientificIdentifier(
            "fixture", "measurement-identity", f"velocity-{name}", "1"
        ),
        source_acquisition_id=InstanceIdentifier("acquisition", name),
        samples=tuple(SprintVelocitySample(time, velocity) for time, velocity in samples),
        timebase=timebase,
        support=support,
    )
    artifact = _artifact(name, series.canonical_content_digest)
    acquisition = _acquisition(name, device=device, modality=modality)
    evidence = build_velocity_series_evidence(
        observation_id=InstanceIdentifier("observation", name),
        context=_context(f"context-{name}", test_instance="maximum-speed", trial=None),
        protocol=protocol,
        series=series,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    result = sampled_maximum_velocity(evidence)
    assert isinstance(result, MaximumSprintVelocityResult)
    return result, series


def test_sampled_maximum_velocity_and_series_digest_gold_fixture() -> None:
    result, series = _velocity_evidence("velocity-gold")
    assert result.value == pytest.approx(7.2)
    assert result.evidence.series.canonical_content_digest == series.canonical_content_digest
    assert refuse_sampled_maximum_as_sustained_maximum().blocks_claim
    restored = from_canonical_json(canonical_json(result), MaximumSprintVelocityResult)
    assert restored == result
    assert canonical_hash(restored) == canonical_hash(result)

    with pytest.raises(ValueError):
        replace(
            series,
            samples=(
                SprintVelocitySample(0.0, 3.0),
                SprintVelocitySample(0.1, 5.0),
                SprintVelocitySample(0.2, 7.3),
                SprintVelocitySample(0.3, 6.0),
            ),
        )


def test_maximum_speed_cross_device_comparison_requires_bridge() -> None:
    radar, _ = _velocity_evidence("radar-result", device="radar-1")
    gnss, _ = _velocity_evidence(
        "gnss-result",
        device="gnss-1",
        modality=FieldTestSensorModality.GNSS_GPS,
    )
    comparison = compare_maximum_sprint_velocity(radar, gnss)
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED


def _505_trials(side: object, prefix: str, values: tuple[float, float, float]) -> Standard505Result:
    protocol = standard_505_protocol_v1()
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    assert isinstance(side, FieldTestSide)

    def build_one(index: int, value: float) -> Standard505TrialObservation:
        trial = build_standard_505_trial_observation(
            observation_id=InstanceIdentifier("observation", f"{prefix}-{index}"),
            context=_context(
                f"context-{prefix}-{index}", test_instance="505", trial=f"{prefix}-{index}"
            ),
            protocol=protocol,
            side=side,
            time_seconds=value,
            source_artifact=_artifact(f"{prefix}-{index}"),
            acquisition=_acquisition(f"{prefix}-{index}"),
        )
        qualification = normalize_field_test_qualification(
            _qualification_observation(trial.observation),
            trial.observation,
        )
        return replace(trial, source_qualification=qualification)

    trials = tuple(build_one(index, value) for index, value in enumerate(values, 1))
    result = aggregate_standard_505_trials(trials)
    assert isinstance(result, Standard505Result)
    return result


def _linear_reference(*, athlete: str = "athlete-1") -> SprintTimeObservation:
    protocol = linear_sprint_30m_protocol_v1()
    trials = tuple(
        _qualified_sprint_trial(
            f"reference-{index}",
            protocol=protocol,
            time_seconds=value,
            test_instance="linear-reference",
            athlete=athlete,
        )
        for index, value in enumerate((1.8, 1.9, 2.0), 1)
    )
    reference = aggregate_linear_sprint_30m_reference(trials)
    assert isinstance(reference, SprintTimeObservation)
    return reference


def test_standard_505_and_cod_deficit_gold_fixture() -> None:
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    left = _505_trials(FieldTestSide.LEFT, "left", (2.4, 2.5, 2.6))
    right = _505_trials(FieldTestSide.RIGHT, "right", (2.5, 2.6, 2.7))
    assert left.time_seconds == pytest.approx(2.5)
    assert right.time_seconds == pytest.approx(2.6)
    assert left.observation.context.trial_id is None

    deficit = calculate_cod_deficit(left, _linear_reference())
    assert isinstance(deficit, CODDeficitResult)
    assert deficit.value == pytest.approx(0.6)
    assert deficit.observation.context.trial_id is None
    assert len(deficit.source_observations) == 2
    assert refuse_505_asymmetry().blocks_claim


def test_standard_505_side_and_arbitrary_reference_attacks_refuse() -> None:
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    left = _505_trials(FieldTestSide.LEFT, "attack-left", (2.4, 2.5, 2.6))
    with pytest.raises(ValueError):
        replace(left, side=FieldTestSide.RIGHT)
    single = _qualified_sprint_trial(
        "arbitrary-10m",
        protocol=linear_sprint_30m_protocol_v1(),
        time_seconds=1.9,
        test_instance="linear-reference",
    )
    refused = calculate_cod_deficit(left, single)
    assert not isinstance(refused, CODDeficitResult)


def _rsa_protocol_four() -> RSAProtocolIdentity:
    return RSAProtocolIdentity(
        family=FieldTestFamily.REPEATED_SPRINT_ABILITY,
        protocol_version="1.0.0",
        reference=_ref("protocol", "rsa-four-linear-fixture"),
        movement_mode=RSAMovementMode.LINEAR,
        sprint_distance_m=30.0,
        shuttle_layout=None,
        cod_count=0,
        turn_angle_deg=None,
        repetitions=4,
        recovery_duration_s=30.0,
        recovery_mode=RSARecoveryMode.ACTIVE_WALK,
    )


def _rsa_repetitions() -> tuple[RSARepetitionObservation, ...]:
    from dynamislm.measurement.field_testing.rsa import rsa_6x40m_shuttle_protocol_v1

    protocol = rsa_6x40m_shuttle_protocol_v1()
    repetitions = []
    for index, value in enumerate((4.00, 4.10, 4.20, 4.30, 4.40, 4.50), 1):
        name = f"rsa-{index}"
        repetition = build_rsa_repetition_observation(
            observation_id=InstanceIdentifier("observation", name),
            context=_context(f"context-{name}", test_instance="rsa", trial=name),
            protocol=protocol,
            set_id=InstanceIdentifier("rsa-set", "rsa-fixture"),
            sprint_index=index,
            time_seconds=value,
            source_artifact=_artifact(name),
            acquisition=_acquisition(name),
        )
        qualification = normalize_field_test_qualification(
            _qualification_observation(repetition.observation),
            repetition.observation,
        )
        repetitions.append(replace(repetition, source_qualification=qualification))
    return tuple(repetitions)


def _rsa_criterion(
    repetitions: tuple[RSARepetitionObservation, ...],
    *,
    criterion_time: float = 4.0,
    athlete: str = "athlete-1",
    test_instance: str = "rsa",
) -> RSACriterionSprintEvidence:
    first = repetitions[0]
    criterion_observation = build_rsa_criterion_sprint_source_observation(
        observation_id=InstanceIdentifier("observation", "rsa-criterion"),
        context=_context(
            "context-rsa-criterion",
            test_instance=test_instance,
            trial="rsa-criterion",
            athlete=athlete,
        ),
        protocol=first.protocol,
        set_id=first.set_id,
        time_seconds=criterion_time,
        source_artifact=_artifact("rsa-criterion"),
        acquisition=_acquisition("rsa-criterion"),
    )
    qualification = _qualification_observation(criterion_observation)
    return build_rsa_criterion_sprint_evidence(
        source_observation=criterion_observation,
        source_qualification_observation=qualification,
        set_id=first.set_id,
    )


def test_rsa_best_mean_total_and_percent_decrement_gold_fixture() -> None:
    repetitions = _rsa_repetitions()
    criterion = _rsa_criterion(repetitions)
    best = calculate_rsa_best_time(repetitions, criterion)
    mean = calculate_rsa_mean_time(repetitions, criterion)
    total = calculate_rsa_total_time(repetitions, criterion)
    decrement = calculate_rsa_percent_decrement(repetitions, criterion)
    assert isinstance(best, RSAResult) and best.value == pytest.approx(4.00)
    assert isinstance(mean, RSAResult) and mean.value == pytest.approx(4.25)
    assert isinstance(total, RSAResult) and total.value == pytest.approx(25.50)
    assert isinstance(decrement, RSAResult) and decrement.value == pytest.approx(6.25)
    assert decrement.observation.identity.semantic.measurand == RSA_PERCENT_DECREMENT_MEASURAND
    assert compare_rsa_results(best, mean).state is ComparabilityState.NOT_COMPARABLE
    assert refuse_rsa_decrement_as_fatigue().blocks_claim
    assert refuse_alternate_rsa_decrement().blocks_claim


def test_rsa_missing_middle_or_duplicate_repetition_refuses() -> None:
    repetitions = _rsa_repetitions()
    criterion = _rsa_criterion(repetitions)
    missing = repetitions[:1] + repetitions[2:]
    refused = calculate_rsa_total_time(missing, criterion)
    assert not isinstance(refused, RSAResult)
    duplicate = build_rsa_repetition_observation(
        observation_id=InstanceIdentifier("observation", "rsa-duplicate"),
        context=_context("context-rsa-duplicate", test_instance="rsa", trial="rsa-duplicate"),
        protocol=repetitions[0].protocol,
        set_id=repetitions[0].set_id,
        sprint_index=2,
        time_seconds=4.25,
        source_artifact=_artifact("rsa-duplicate"),
        acquisition=_acquisition("rsa-duplicate"),
    )
    duplicate = replace(
        duplicate,
        source_qualification=normalize_field_test_qualification(
            _qualification_observation(duplicate.observation), duplicate.observation
        ),
    )
    refused_duplicate = calculate_rsa_total_time(
        (repetitions[0], repetitions[1], duplicate, repetitions[3], repetitions[4], repetitions[5]),
        criterion,
    )
    assert not isinstance(refused_duplicate, RSAResult)


def _ift_test() -> IFTTestEvidence:
    protocol = ift30_15_protocol_v1()
    stages = []
    for index in range(1, 7):
        name = f"ift-stage-{index}"
        artifact = _artifact(name)
        acquisition = _acquisition(
            name,
            device="ift-audio",
            modality=FieldTestSensorModality.SOURCE_REPORTED,
        )
        stage_observation = build_ift_stage_source_observation(
            observation_id=InstanceIdentifier("observation", name),
            context=_context(f"context-{name}", test_instance="ift", trial=None),
            protocol=protocol,
            stage_index=index,
            source_artifact=artifact,
            acquisition=acquisition,
        )
        completion_evidence = build_ift_stage_completion_source_observation(
            stage_observation=stage_observation,
            reported_completion=(
                IFTStageCompletion.COMPLETED if index < 6 else IFTStageCompletion.NOT_COMPLETED
            ),
            reported_miss_count=0 if index < 6 else 3,
            source_artifact=artifact,
            acquisition=acquisition,
        )
        stages.append(
            build_ift_stage_evidence(
                stage_observation=stage_observation,
                completion_evidence=completion_evidence,
                source_qualification_observation=_qualification_observation(stage_observation),
            )
        )
    termination_observation = build_ift_termination_source_observation(
        target_stage=stages[-1],
        reported_reason=IFTTerminationReason.THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES,
        source_artifact=_artifact("ift-termination"),
        acquisition=_acquisition(
            "ift-termination",
            device="ift-audio",
            modality=FieldTestSensorModality.SOURCE_REPORTED,
        ),
    )
    termination = build_ift_termination_evidence(
        termination_observation=termination_observation,
        target_stage=stages[-1],
    )
    return build_ift_test_evidence(
        test_id=InstanceIdentifier("ift-test", "ift-fixture"),
        protocol=protocol,
        stages=tuple(stages),
        termination=termination,
    )


def test_30_15_ift_vift_gold_fixture_and_refusals() -> None:
    test = _ift_test()
    result = calculate_vift(test)
    assert isinstance(result, VIFTResult)
    assert result.value_kmh == pytest.approx(10.0)
    assert result.final_completed_stage == 5
    assert result.observation.context.trial_id is None
    assert isinstance(from_canonical_json(canonical_json(result), VIFTResult), VIFTResult)
    assert refuse_vift_as_vo2max().blocks_claim
    assert refuse_vift_as_mas().blocks_claim
    assert refuse_vift_as_mss().blocks_claim


def test_30_15_ift_stage_completion_and_protocol_tampering_refuse() -> None:
    test = _ift_test()
    assert "completion" not in signature(build_ift_stage_evidence).parameters
    assert "miss_count" not in signature(build_ift_stage_evidence).parameters
    incomplete = test.stages[-1]
    assert incomplete.completion is IFTStageCompletion.NOT_COMPLETED
    assert incomplete.target_stage_velocity_kmh == pytest.approx(10.5)
    with pytest.raises(ValueError):
        replace(
            test,
            termination=replace(
                test.termination,
                observation=replace(
                    test.termination.observation,
                    result=replace(
                        test.termination.observation.result,
                        value=CategoricalValue(IFTTerminationReason.VOLUNTARY_EXHAUSTION.value),
                    ),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(ift30_15_protocol_v1(), course_length_m=28.0)
    assert IFT30_15_PROTOCOL_V1.identifier.key == "30-15-ift-40m-v1"


def test_serialization_version_and_distinct_registry_identities() -> None:
    assert SECOND.identifier.key == "second"
    assert SHORT_LINEAR_SPRINT_TEST_FAMILY != RSA_TEST_FAMILY
    assert SHORT_LINEAR_SPRINT_CONSTRUCT != RSA_CONSTRUCT
    assert SPLIT_TIME_MEASURAND != SECOND  # type: ignore[comparison-overlap]
    assert LINEAR_SPRINT_30M_PROTOCOL_V1.identifier.object_type == "protocol"


@pytest.mark.parametrize(
    "builder",
    (
        build_source_qualification_observation,
        build_standard_505_trial_observation,
        qualify_standard_505_trial,
        build_rsa_repetition_observation,
        qualify_rsa_repetition,
        build_ift_stage_evidence,
        qualify_ift_stage,
        build_ift_termination_evidence,
        build_ift_test_evidence,
    ),
    ids=(
        "qualification-normalizer",
        "505-source-builder",
        "505-qualifier",
        "rsa-source-builder",
        "rsa-qualifier",
        "ift-stage-normalizer",
        "ift-stage-qualifier",
        "ift-termination-normalizer",
        "ift-test-normalizer",
    ),
)
def test_adjudication_apis_have_no_caller_verdict_parameter(
    builder: Callable[..., object],
) -> None:
    parameters = signature(builder).parameters
    assert "status" not in parameters
    assert "qualification_status" not in parameters
    assert "completion" not in parameters
    assert "miss_count" not in parameters
    assert "reason" not in parameters
    assert "termination_reason" not in parameters


def test_upstream_rejected_qualification_is_preserved_but_cannot_qualify() -> None:
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    result = _505_trials(FieldTestSide.LEFT, "rejected-upstream", (2.4, 2.5, 2.6))
    trial = result.trials[0]
    rejected_observation = _qualification_observation(
        trial.observation,
        status=FieldTestQualificationStatus.REJECTED,
    )
    rejected = normalize_field_test_qualification(rejected_observation, trial.observation)
    assert rejected.status is FieldTestQualificationStatus.REJECTED
    with pytest.raises(ValueError):
        qualify_standard_505_trial(trial, source_observation=rejected_observation)


def test_source_qualification_target_context_source_and_provenance_rebinding_refuse() -> None:
    target = _qualified_sprint_trial(
        "qualification-target",
        protocol=linear_sprint_30m_protocol_v1(),
        time_seconds=1.8,
    )
    other = _qualified_sprint_trial(
        "qualification-other",
        protocol=linear_sprint_30m_protocol_v1(),
        time_seconds=1.9,
    )
    source = _qualification_observation(target.observation)
    with pytest.raises(ValueError):
        normalize_field_test_qualification(source, other.observation)
    with pytest.raises(ValueError):
        normalize_field_test_qualification(
            replace(source, context=other.observation.context),
            target.observation,
        )
    with pytest.raises(ValueError):
        normalize_field_test_qualification(
            build_field_test_qualification_source_observation(
                target_observation=target.observation,
                reported_status=FieldTestQualificationStatus.QUALIFIED,
                source_artifact=_artifact("qualification-unbound"),
                acquisition=_acquisition("qualification-unbound"),
            ),
            target.observation,
        )
    tampered_artifact = _artifact("qualification-target", "sha256:tampered")
    tampered = build_field_test_qualification_source_observation(
        target_observation=target.observation,
        reported_status=FieldTestQualificationStatus.QUALIFIED,
        source_artifact=tampered_artifact,
        acquisition=_acquisition("qualification-target"),
    )
    with pytest.raises(ValueError):
        normalize_field_test_qualification(tampered, target.observation)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("start_trigger", _ref("trigger", "different-start")),
        ("finish_trigger", _ref("trigger", "different-finish")),
        ("start_line_offset_m", 0.50),
        ("start_initiation_mode", StartInitiationMode.FIRST_MOVEMENT),
        ("reaction_time_semantics", ReactionTimeSemantics.INCLUDED),
        ("timing_device", _ref("device", "different-timing-device")),
        ("gate_topology", TimingGateTopology.DUAL_BEAM),
        ("surface", "different-surface"),
    ),
    ids=(
        "start-trigger",
        "finish-trigger",
        "start-offset",
        "start-semantics",
        "reaction-semantics",
        "timing-device",
        "gate-topology",
        "surface",
    ),
)
def test_sprint_protocol_identity_attacks_refuse(field: str, value: object) -> None:
    protocol = linear_sprint_30m_protocol_v1()
    start = _qualified_sprint_trial(
        "protocol-attack-start",
        protocol=protocol,
        time_seconds=1.0,
        end_m=5.0,
        trial_id="same-trial",
    )
    changed_protocol = _replace_any(protocol, **{field: value})
    end = _qualified_sprint_trial(
        "protocol-attack-end",
        protocol=changed_protocol,
        time_seconds=1.8,
        trial_id="same-trial",
    )
    refused = derive_interval_split(start, end)
    assert not isinstance(refused, SprintTimeObservation)


@pytest.mark.parametrize(
    "end_m",
    (4.0, 15.0, 30.0),
    ids=("wrong-short-distance", "wrong-approach-distance", "wrong-full-distance"),
)
def test_sprint_split_distance_and_segment_rebinding_refuse(end_m: float) -> None:
    protocol = linear_sprint_30m_protocol_v1()
    source = _qualified_sprint_trial(
        f"distance-source-{end_m:g}",
        protocol=protocol,
        time_seconds=1.0,
        end_m=5.0,
        trial_id="distance-trial",
    )
    target = _qualified_sprint_trial(
        f"distance-target-{end_m:g}",
        protocol=protocol,
        time_seconds=1.8,
        end_m=end_m,
        trial_id="distance-trial",
    )
    interval = derive_interval_split(source, target)
    if end_m <= 5.0:
        assert not isinstance(interval, SprintTimeObservation)
        return
    assert isinstance(interval, SprintTimeObservation)
    refused = derive_segment_average_velocity(
        interval,
        FieldTestingSegmentDefinition("rebound", 0.0, end_m - 1.0),
    )
    assert not isinstance(refused, SegmentAverageVelocityResult)


@pytest.mark.parametrize(
    "attack",
    ("arbitrary-scalar", "incompatible-clock", "segment-as-maximum", "split-as-acceleration"),
)
def test_sprint_arbitrary_scalar_clock_and_relabel_attacks_refuse(attack: str) -> None:
    protocol = linear_sprint_30m_protocol_v1()
    if attack == "arbitrary-scalar":
        with pytest.raises(ValueError):
            SprintTimeObservation(0.8, cumulative_split(10.0))  # type: ignore[arg-type]
    elif attack == "incompatible-clock":
        start = _qualified_sprint_trial(
            "clock-start",
            protocol=protocol,
            time_seconds=1.0,
            end_m=5.0,
            trial_id="clock-trial",
        )
        changed = replace(
            protocol,
            timebase=FieldTestingTimebase(
                kind=FieldTestTimebaseKind.EXPLICIT,
                times_s=(0.0, 0.01),
            ),
        )
        end = _qualified_sprint_trial(
            "clock-end",
            protocol=changed,
            time_seconds=1.8,
            trial_id="clock-trial",
        )
        assert not isinstance(derive_interval_split(start, end), SprintTimeObservation)
    elif attack == "segment-as-maximum":
        assert refuse_segment_average_velocity_as_max_speed().blocks_claim
    else:
        assert refuse_sprint_acceleration().blocks_claim


@pytest.mark.parametrize(
    "attack",
    (
        "sampling",
        "filtering",
        "smoothing",
        "interpolation",
        "support",
        "estimator",
        "source-provenance",
    ),
)
def test_maximum_speed_series_identity_attacks_refuse(attack: str) -> None:
    result, series = _velocity_evidence(f"maximum-attack-{attack}")
    if attack == "sampling":
        with pytest.raises(ValueError):
            replace(
                series,
                sampling=SamplingCharacteristics(frequency_hz=100.0),
            )
    elif attack == "support":
        with pytest.raises(ValueError):
            replace(
                series,
                support=replace(series.support, end_index=series.support.end_index - 1),
            )
    elif attack == "source-provenance":
        changed_artifact = _artifact(
            f"maximum-attack-{attack}",
            "sha256:source-provenance-tampered",
        )
        with pytest.raises(ValueError):
            SprintVelocitySeriesEvidence(
                observation=result.evidence.observation,
                series=result.evidence.series,
                source_artifact=changed_artifact,
                acquisition=result.evidence.acquisition,
            )
    else:
        identity = result.observation.identity
        processing = identity.processing
        if attack == "filtering":
            changed_processing = _replace_any(processing, filtering=(_ref("filter", "changed"),))
        elif attack == "smoothing":
            changed_processing = _replace_any(processing, smoothing=_ref("smoothing", "changed"))
        elif attack == "interpolation":
            changed_processing = _replace_any(
                processing, interpolation=_ref("interpolation", "changed")
            )
        else:
            changed_processing = _replace_any(processing, estimator=_ref("estimator", "changed"))
        changed_observation = replace(
            result.observation,
            identity=replace(identity, processing=changed_processing),
        )
        with pytest.raises(ValueError):
            MaximumSprintVelocityResult(changed_observation, result.evidence)


@pytest.mark.parametrize(
    "field",
    (
        "approach_distance_m",
        "timed_entry_distance_m",
        "turn_angle_deg",
        "timed_exit_distance_m",
        "timing_start_before_turn_m",
    ),
)
def test_standard_505_geometry_attacks_refuse(field: str) -> None:
    protocol = standard_505_protocol_v1()
    with pytest.raises(ValueError):
        _replace_any(protocol, **{field: 1.0})


def test_standard_505_unqualified_and_context_attacks_refuse() -> None:
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    protocol = standard_505_protocol_v1()
    raw_trials = tuple(
        build_standard_505_trial_observation(
            observation_id=InstanceIdentifier("observation", f"raw-505-{index}"),
            context=_context(
                f"context-raw-505-{index}",
                test_instance="505",
                trial=f"raw-505-{index}",
            ),
            protocol=protocol,
            side=FieldTestSide.LEFT,
            time_seconds=2.4 + index / 10.0,
            source_artifact=_artifact(f"raw-505-{index}"),
            acquisition=_acquisition(f"raw-505-{index}"),
        )
        for index in range(1, 4)
    )
    assert not isinstance(aggregate_standard_505_trials(raw_trials), Standard505Result)
    qualified = _505_trials(FieldTestSide.LEFT, "context-505", (2.4, 2.5, 2.6))
    with pytest.raises(ValueError):
        replace(
            qualified.trials[0],
            observation=replace(
                qualified.trials[0].observation,
                context=_context(
                    "rebound-505",
                    test_instance="505",
                    trial="context-505-1",
                    athlete="other",
                ),
            ),
        )


def test_cod_deficit_cross_athlete_and_no_first_source_context_inheritance_refuse() -> None:
    from dynamislm.measurement.field_testing.identity import FieldTestSide

    result = _505_trials(FieldTestSide.LEFT, "cod-context", (2.4, 2.5, 2.6))
    reference = _linear_reference(athlete="athlete-2")
    assert not isinstance(calculate_cod_deficit(result, reference), CODDeficitResult)
    same_reference = _linear_reference()
    deficit = calculate_cod_deficit(result, same_reference)
    assert isinstance(deficit, CODDeficitResult)
    assert deficit.observation.context.context_id != result.observation.context.context_id
    assert (
        deficit.observation.context.test_instance_id != result.observation.context.test_instance_id
    )


@pytest.mark.parametrize(
    "field",
    (
        "sprint_distance_m",
        "cod_count",
        "turn_angle_deg",
        "repetitions",
        "recovery_duration_s",
        "recovery_mode",
        "start_initiation_mode",
        "reaction_time_semantics",
    ),
)
def test_rsa_protocol_evidence_attacks_refuse(field: str) -> None:
    protocol = rsa_6x40m_shuttle_protocol_v1()
    values: dict[str, object] = {
        "sprint_distance_m": 30.0,
        "cod_count": 0,
        "turn_angle_deg": 90.0,
        "repetitions": 5,
        "recovery_duration_s": 30.0,
        "recovery_mode": RSARecoveryMode.ACTIVE_WALK,
        "start_initiation_mode": StartInitiationMode.SELF_INITIATED_PHOTOCELL_CROSSING,
        "reaction_time_semantics": ReactionTimeSemantics.EXCLUDED,
    }
    with pytest.raises(ValueError):
        _replace_any(protocol, **{field: values[field]})


@pytest.mark.parametrize(
    "variant",
    ("wrong-count", "missing", "duplicate", "out-of-order"),
)
def test_rsa_repetition_series_attacks_refuse(variant: str) -> None:
    repetitions = _rsa_repetitions()
    criterion = _rsa_criterion(repetitions)
    if variant == "wrong-count" or variant == "missing":
        candidate = repetitions[:-1]
    elif variant == "duplicate":
        candidate = (repetitions[0], repetitions[1], repetitions[1], *repetitions[3:])
    else:
        candidate = tuple(reversed(repetitions))
    assert not isinstance(calculate_rsa_total_time(candidate, criterion), RSAResult)


def test_rsa_criterion_is_required_and_first_repetition_validity_is_deterministic() -> None:
    repetitions = _rsa_repetitions()
    assert not isinstance(calculate_rsa_total_time(repetitions), RSAResult)
    slow_criterion = _rsa_criterion(repetitions, criterion_time=3.8)
    assert not isinstance(calculate_rsa_total_time(repetitions, slow_criterion), RSAResult)


@pytest.mark.parametrize("variant", ("wrong-athlete", "wrong-test", "unqualified"))
def test_rsa_criterion_binding_attacks_refuse(variant: str) -> None:
    repetitions = _rsa_repetitions()
    if variant == "wrong-athlete":
        criterion = _rsa_criterion(repetitions, athlete="athlete-2")
        assert not isinstance(calculate_rsa_total_time(repetitions, criterion), RSAResult)
    elif variant == "wrong-test":
        criterion = _rsa_criterion(repetitions, test_instance="other-rsa")
        assert not isinstance(calculate_rsa_total_time(repetitions, criterion), RSAResult)
    else:
        raw_criterion = build_rsa_criterion_sprint_source_observation(
            observation_id=InstanceIdentifier("observation", "rsa-unqualified-criterion"),
            context=_context(
                "context-rsa-unqualified-criterion",
                test_instance="rsa",
                trial="rsa-unqualified-criterion",
            ),
            protocol=repetitions[0].protocol,
            set_id=repetitions[0].set_id,
            time_seconds=4.0,
            source_artifact=_artifact("rsa-unqualified-criterion"),
            acquisition=_acquisition("rsa-unqualified-criterion"),
        )
        with pytest.raises(ValueError):
            build_rsa_criterion_sprint_evidence(
                source_observation=raw_criterion,
                source_qualification_observation=_qualification_observation(
                    raw_criterion,
                    status=FieldTestQualificationStatus.REJECTED,
                ),
                set_id=repetitions[0].set_id,
            )


def test_rsa_criterion_device_and_qualification_tampering_refuse() -> None:
    repetitions = _rsa_repetitions()
    criterion = _rsa_criterion(repetitions)
    changed_identity = replace(
        repetitions[0].observation.identity,
        acquisition=replace(
            repetitions[0].observation.identity.acquisition,
            device=_ref("device", "rsa-different-device"),
        ),
    )
    changed_repetition = replace(
        repetitions[0],
        observation=replace(repetitions[0].observation, identity=changed_identity),
    )
    candidate = (changed_repetition, *repetitions[1:])
    assert not isinstance(calculate_rsa_total_time(candidate, criterion), RSAResult)
    with pytest.raises(ValueError):
        replace(criterion, set_id=InstanceIdentifier("rsa-set", "rebound-set"))


def test_rsa_percent_decrement_measurand_and_equation_boundaries_refuse() -> None:
    repetitions = _rsa_repetitions()
    criterion = _rsa_criterion(repetitions)
    decrement = calculate_rsa_percent_decrement(repetitions, criterion)
    assert isinstance(decrement, RSAResult)
    bad_identity = replace(
        decrement.observation.identity,
        semantic=replace(
            decrement.observation.identity.semantic,
            measurand=SPLIT_TIME_MEASURAND,
        ),
    )
    with pytest.raises(ValueError):
        RSAResult(
            replace(decrement.observation, identity=bad_identity),
            decrement.metric,
            decrement.repetitions,
            criterion,
        )
    assert refuse_alternate_rsa_decrement().blocks_claim
    assert refuse_rsa_decrement_as_fatigue().blocks_claim


@pytest.mark.parametrize(
    "field",
    (
        "initial_velocity_kmh",
        "stage_increment_kmh",
        "run_interval_s",
        "recovery_interval_s",
        "course_length_m",
        "control_zone_m",
    ),
)
def test_ift_canonical_protocol_attacks_refuse(field: str) -> None:
    protocol = ift30_15_protocol_v1()
    values = {
        "initial_velocity_kmh": 7.5,
        "stage_increment_kmh": 1.0,
        "run_interval_s": 28.0,
        "recovery_interval_s": 10.0,
        "course_length_m": 28.0,
        "control_zone_m": 2.0,
    }
    with pytest.raises(ValueError):
        _replace_any(protocol, **{field: values[field]})


def test_ift_completion_termination_context_and_provenance_attacks_refuse() -> None:
    test = _ift_test()
    first = test.stages[0]
    last = test.stages[-1]
    with pytest.raises(ValueError):
        build_ift_stage_evidence(
            stage_observation=first.observation,
            completion_evidence=last.completion_evidence,
            source_qualification_observation=_qualification_observation(first.observation),
        )
    with pytest.raises(ValueError):
        build_ift_stage_evidence(
            stage_observation=replace(
                first.observation,
                context=_context("ift-rebound", test_instance="ift", trial=None, athlete="other"),
            ),
            completion_evidence=first.completion_evidence,
        )
    termination_observation = build_ift_termination_source_observation(
        target_stage=last,
        reported_reason=IFTTerminationReason.VOLUNTARY_EXHAUSTION,
        source_artifact=_artifact("ift-rebound-termination"),
        acquisition=_acquisition(
            "ift-rebound-termination",
            device="ift-audio",
            modality=FieldTestSensorModality.SOURCE_REPORTED,
        ),
    )
    with pytest.raises(ValueError):
        build_ift_termination_evidence(
            termination_observation=termination_observation,
            target_stage=first,
        )


def test_ift_miss_count_does_not_authorize_consecutive_failure_or_arbitrary_vift() -> None:
    test = _ift_test()
    assert test.stages[-1].miss_count == 3
    assert test.termination.reason is IFTTerminationReason.THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES
    assert "value" not in signature(calculate_vift).parameters
    result = calculate_vift(test)
    assert isinstance(result, VIFTResult)
    assert result.value_kmh == pytest.approx(10.0)
