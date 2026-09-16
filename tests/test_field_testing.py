"""RES-67 numerical gold fixtures and adversarial scientific-boundary tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from dynamislm.comparability.models import ComparabilityState
from dynamislm.measurement.field_testing.cod import (
    CODDeficitResult,
    Standard505Result,
    aggregate_standard_505_trials,
    build_standard_505_trial_observation,
    calculate_cod_deficit,
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
)
from dynamislm.measurement.field_testing.ift import (
    IFTStageCompletion,
    IFTTerminationReason,
    IFTTestEvidence,
    VIFTResult,
    build_ift_stage_evidence,
    build_ift_test_evidence,
    calculate_vift,
    ift30_15_protocol_v1,
    refuse_vift_as_mas,
    refuse_vift_as_mss,
    refuse_vift_as_vo2max,
)
from dynamislm.measurement.field_testing.registry import (
    IFT30_15_PROTOCOL_V1,
    LINEAR_SPRINT_30M_PROTOCOL_V1,
    METER_PER_SECOND,
    RSA_CONSTRUCT,
    RSA_TEST_FAMILY,
    SECOND,
    SHORT_LINEAR_SPRINT_CONSTRUCT,
    SHORT_LINEAR_SPRINT_TEST_FAMILY,
    SPLIT_TIME_MEASURAND,
)
from dynamislm.measurement.field_testing.rsa import (
    RSAMovementMode,
    RSAProtocolIdentity,
    RSARecoveryMode,
    RSARepetitionObservation,
    RSAResult,
    build_rsa_repetition_observation,
    calculate_rsa_best_time,
    calculate_rsa_mean_time,
    calculate_rsa_percent_decrement,
    calculate_rsa_total_time,
    refuse_alternate_rsa_decrement,
    refuse_rsa_decrement_as_fatigue,
)
from dynamislm.measurement.field_testing.sprint import (
    MaximumSprintVelocityResult,
    SegmentAverageVelocityResult,
    SprintSplitKind,
    SprintTimeObservation,
    SprintVelocitySample,
    SprintVelocitySeries,
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
    ScientificIdentifier,
)
from dynamislm.measurement.observation import ObservationContext
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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


def _qualified_sprint_trial(
    name: str,
    *,
    protocol: FieldTestingProtocolIdentity,
    time_seconds: float,
    end_m: float = 10.0,
    test_instance: str = "linear",
    trial_id: str | None = None,
) -> SprintTimeObservation:
    artifact = _artifact(name)
    acquisition = _acquisition(name)
    source = build_sprint_time_observation(
        observation_id=InstanceIdentifier("observation", name),
        context=_context(
            f"context-{name}",
            test_instance=test_instance,
            trial=name if trial_id is None else trial_id,
        ),
        protocol=protocol,
        split=cumulative_split(end_m),
        time_seconds=time_seconds,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    from dynamislm.measurement.field_testing._common import build_source_qualification_observation

    qualification = build_source_qualification_observation(
        target_observation=source.observation,
        status=FieldTestQualificationStatus.QUALIFIED,
        source_artifact=artifact,
        acquisition=acquisition,
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
    trials = tuple(
        build_standard_505_trial_observation(
            observation_id=InstanceIdentifier("observation", f"{prefix}-{index}"),
            context=_context(
                f"context-{prefix}-{index}", test_instance="505", trial=f"{prefix}-{index}"
            ),
            protocol=protocol,
            side=side,
            time_seconds=value,
            source_artifact=_artifact(f"{prefix}-{index}"),
            acquisition=_acquisition(f"{prefix}-{index}"),
            qualification_status=FieldTestQualificationStatus.QUALIFIED,
        )
        for index, value in enumerate(values, 1)
    )
    result = aggregate_standard_505_trials(trials)
    assert isinstance(result, Standard505Result)
    return result


def _linear_reference() -> SprintTimeObservation:
    protocol = linear_sprint_30m_protocol_v1()
    trials = tuple(
        _qualified_sprint_trial(
            f"reference-{index}",
            protocol=protocol,
            time_seconds=value,
            test_instance="linear-reference",
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
    protocol = _rsa_protocol_four()
    repetitions = []
    for index, value in enumerate((4.00, 4.10, 4.20, 4.30), 1):
        name = f"rsa-{index}"
        repetitions.append(
            build_rsa_repetition_observation(
                observation_id=InstanceIdentifier("observation", name),
                context=_context(f"context-{name}", test_instance="rsa", trial=name),
                protocol=protocol,
                set_id=InstanceIdentifier("rsa-set", "rsa-fixture"),
                sprint_index=index,
                time_seconds=value,
                source_artifact=_artifact(name),
                acquisition=_acquisition(name),
                qualification_status=FieldTestQualificationStatus.QUALIFIED,
            )
        )
    return tuple(repetitions)


def test_rsa_best_mean_total_and_percent_decrement_gold_fixture() -> None:
    repetitions = _rsa_repetitions()
    best = calculate_rsa_best_time(repetitions)
    mean = calculate_rsa_mean_time(repetitions)
    total = calculate_rsa_total_time(repetitions)
    decrement = calculate_rsa_percent_decrement(repetitions)
    assert isinstance(best, RSAResult) and best.value == pytest.approx(4.00)
    assert isinstance(mean, RSAResult) and mean.value == pytest.approx(4.15)
    assert isinstance(total, RSAResult) and total.value == pytest.approx(16.60)
    assert isinstance(decrement, RSAResult) and decrement.value == pytest.approx(3.75)
    assert compare_rsa_results(best, mean).state is ComparabilityState.NOT_COMPARABLE
    assert refuse_rsa_decrement_as_fatigue().blocks_claim
    assert refuse_alternate_rsa_decrement().blocks_claim


def test_rsa_missing_middle_or_duplicate_repetition_refuses() -> None:
    repetitions = _rsa_repetitions()
    missing = repetitions[:1] + repetitions[2:]
    refused = calculate_rsa_total_time(missing)
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
        qualification_status=FieldTestQualificationStatus.QUALIFIED,
    )
    refused_duplicate = calculate_rsa_total_time(
        (repetitions[0], repetitions[1], duplicate, repetitions[3])
    )
    assert not isinstance(refused_duplicate, RSAResult)


def _ift_test() -> IFTTestEvidence:
    protocol = ift30_15_protocol_v1()
    stages = []
    for index in range(1, 7):
        name = f"ift-stage-{index}"
        stages.append(
            build_ift_stage_evidence(
                observation_id=InstanceIdentifier("observation", name),
                context=_context(f"context-{name}", test_instance="ift", trial=None),
                protocol=protocol,
                stage_index=index,
                completion=(
                    IFTStageCompletion.COMPLETED if index < 6 else IFTStageCompletion.NOT_COMPLETED
                ),
                miss_count=0 if index < 6 else 3,
                source_artifact=_artifact(name),
                acquisition=_acquisition(
                    name,
                    device="ift-audio",
                    modality=FieldTestSensorModality.SOURCE_REPORTED,
                ),
                qualification_status=FieldTestQualificationStatus.QUALIFIED,
            )
        )
    return build_ift_test_evidence(
        test_id=InstanceIdentifier("ift-test", "ift-fixture"),
        protocol=protocol,
        stages=tuple(stages),
        termination_reason=IFTTerminationReason.THREE_CONSECUTIVE_CONTROL_ZONE_FAILURES,
        termination_source_artifact=_artifact("ift-termination"),
        termination_acquisition=_acquisition(
            "ift-termination",
            device="ift-audio",
            modality=FieldTestSensorModality.SOURCE_REPORTED,
        ),
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
    incomplete = test.stages[-1]
    with pytest.raises(ValueError):
        replace(incomplete, completion=IFTStageCompletion.COMPLETED)
    with pytest.raises(ValueError):
        replace(incomplete, target_stage_velocity_kmh=11.0)
    with pytest.raises(ValueError):
        replace(
            test,
            termination=replace(test.termination, reason=IFTTerminationReason.VOLUNTARY_EXHAUSTION),
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
