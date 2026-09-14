from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm import (
    AcquisitionRecord,
    InstanceIdentifier,
    SamplingCharacteristics,
    ScalarValue,
    ValueOrigin,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import ComparabilityState
from dynamislm.measurement.cmj import (
    CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1,
    CMJAsymmetryMetric,
    CMJEventOccurrence,
    CMJForceAsymmetryResult,
    CMJForceInput,
    CMJForceMetric,
    CMJForceMetricResult,
    CMJIntegrationInterval,
    CMJMechanicalSystemContract,
    CMJMetricSupportKind,
    CMJPhaseOccurrence,
    CMJPowerMetric,
    CMJPowerResult,
    CMJRSIModResult,
    CMJTakeoffVelocityResult,
    CMJThresholdDirection,
    DeclaredCandidateTrialSet,
    ExplicitTimebase,
    QualifiedZeroVelocityReference,
    SupportedSystemComVelocityResult,
    TimebaseIdentity,
    TimebaseKind,
    TotalSupportedForceResult,
    TrialSelectionDecision,
    WeighingSegment,
    aggregate_cmj_session,
    calculate_cmj_force_asymmetry,
    calculate_cmj_force_metric,
    calculate_cmj_phase_force_metric,
    calculate_cmj_power_metric,
    calculate_cmj_rsi_mod,
    calculate_cmj_whole_movement_peak_total_supported_vertical_force,
    calculate_cmj_whole_movement_time_mean_total_supported_vertical_force,
    compare_cmj_metric_results,
    construct_cmj_phase_occurrences,
    construct_total_supported_vertical_force,
    create_cmj_raw_observation,
    derive_net_vertical_force,
    derive_physical_system_mass,
    derive_supported_system_com_acceleration,
    derive_supported_system_com_velocity,
    detect_movement_onset,
    detect_takeoff,
    estimate_system_weight,
    estimate_takeoff_velocity_jump_height,
    evaluate_trial_eligibility,
    project_cmj_takeoff_velocity,
    select_trials,
    source_artifact_for_signal,
)
from dynamislm.measurement.cmj.signal import RawVerticalForceSignal, SignalTimebase
from dynamislm.measurement.cmj.weighing import SystemWeightResult
from dynamislm.refusal import RefusalReasonCode, RefusalResult
from test_cmj import (
    _absolute_parameters,
    _bilateral_inputs,
    _local_gravity,
    _mechanics_contract,
    _onset_parameters,
)


def _rebind_samples(
    source: CMJForceInput,
    samples: tuple[float, ...],
    *,
    timebase: SignalTimebase | None = None,
) -> CMJForceInput:
    assert isinstance(source.signal, RawVerticalForceSignal)
    signal = replace(source.signal, samples=samples, timebase=timebase or source.signal.timebase)
    artifact = source_artifact_for_signal(signal)
    acquisition_identity = source.identity.acquisition
    if isinstance(signal.timebase, ExplicitTimebase):
        acquisition_identity = replace(
            acquisition_identity,
            sampling=SamplingCharacteristics(
                None,
                acquisition_identity.sampling.channels
                if acquisition_identity.sampling is not None
                else (),
            ),
            timebase=TimebaseIdentity(TimebaseKind.EXPLICIT, None),
        )
    identity = replace(
        source.identity,
        acquisition=replace(acquisition_identity, raw_artifact=artifact.artifact_id),
    )
    signal = replace(
        signal,
        source_artifact_id=artifact.artifact_id,
        acquisition_identity_id=identity.identity_id,
    )
    device = identity.acquisition.device
    assert device is not None
    acquisition = AcquisitionRecord(
        acquisition_id=signal.acquisition_id,
        device=device,
        source_artifact_id=artifact.artifact_id,
        sensor_channel=signal.channel_id,
        sampling=identity.acquisition.sampling,
        calibration_reference=identity.acquisition.calibration_reference,
        hardware_firmware=identity.acquisition.hardware_firmware,
    )
    observation = create_cmj_raw_observation(
        observation_id=source.observation.observation_id,
        result_id=source.observation.result.result_id,
        context=source.observation.context,
        identity=identity,
        signal=signal,
        source_artifact=artifact,
        acquisition=acquisition,
        recorded_at=source.observation.provenance.recorded_at,
    )
    return CMJForceInput(observation, identity, signal, artifact, acquisition)


def _adjudicate(weight: SystemWeightResult) -> SystemWeightResult:
    qc = replace(weight.qc, acceptability_adjudicated=True)
    quality = replace(
        weight.observation.result.quality,
        flags=qc.quality_flags,
        note="Synthetic fixture-level weighing acceptability adjudication.",
    )
    return replace(
        weight,
        qc=qc,
        observation=replace(
            weight.observation, result=replace(weight.observation.result, quality=quality)
        ),
    )


def _bilateral_fixture(
    *, timebase: SignalTimebase | None = None
) -> tuple[
    CMJForceInput,
    CMJForceInput,
    TotalSupportedForceResult,
    SupportedSystemComVelocityResult,
    tuple[CMJPhaseOccurrence, ...],
    CMJEventOccurrence,
    CMJEventOccurrence,
    CMJMechanicalSystemContract,
]:
    left, right = _bilateral_inputs()
    left = _rebind_samples(
        left,
        (300.0, 300.0, 300.0, 300.0, 250.0, 100.0, 150.0, 1600.0, 3200.0, 0.0),
        timebase=timebase,
    )
    right = _rebind_samples(
        right,
        (400.0, 400.0, 400.0, 400.0, 350.0, 200.0, 250.0, 1700.0, 3300.0, 0.0),
        timebase=timebase,
    )
    total = construct_total_supported_vertical_force(left, right)
    assert isinstance(total, TotalSupportedForceResult)
    segment = WeighingSegment(
        total.signal.signal_id,
        total.source_artifact.artifact_id,
        total.observation.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(total, segment)
    assert isinstance(weight, SystemWeightResult)
    weight = _adjudicate(weight)
    onset = detect_movement_onset(
        total,
        weight,
        _onset_parameters(weight, search_start_index=3, dwell_samples=1),
    )
    assert isinstance(onset, CMJEventOccurrence)
    takeoff = detect_takeoff(
        total,
        _absolute_parameters(
            20.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=1,
            search_start_index=5,
        ),
        onset=onset,
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    contract = _mechanics_contract()
    mass = derive_physical_system_mass(weight, _local_gravity("res65-bilateral"))
    assert not isinstance(mass, RefusalResult)
    net = derive_net_vertical_force(total, weight, contract)
    assert not isinstance(net, RefusalResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert not isinstance(acceleration, RefusalResult)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(
        acceleration,
        interval=CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 9),
        initial_velocity_condition=reference,
    )
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    phases = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert not isinstance(phases, RefusalResult)
    return left, right, total, velocity, phases, onset, takeoff, contract


def _phase_for(
    metric: CMJPowerMetric | CMJAsymmetryMetric, phases: tuple[CMJPhaseOccurrence, ...]
) -> CMJPhaseOccurrence:
    return phases[1 if metric.value.startswith("BRAKING") else 2]


def test_force_metrics_use_total_force_and_exact_phase_support() -> None:
    _, _, total, _, phases, onset, takeoff, _ = _bilateral_fixture()

    whole_peak = calculate_cmj_whole_movement_peak_total_supported_vertical_force(
        total, onset, takeoff
    )
    whole_mean = calculate_cmj_whole_movement_time_mean_total_supported_vertical_force(
        total, onset, takeoff
    )
    braking_peak = calculate_cmj_phase_force_metric(
        total,
        phases[1],
        CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE,
    )
    propulsion_mean = calculate_cmj_phase_force_metric(
        total,
        phases[2],
        CMJForceMetric.PROPULSION_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE,
    )

    assert isinstance(whole_peak, CMJForceMetricResult)
    assert isinstance(whole_mean, CMJForceMetricResult)
    assert isinstance(braking_peak, CMJForceMetricResult)
    assert isinstance(propulsion_mean, CMJForceMetricResult)
    assert whole_peak.value_n == pytest.approx(6500.0)
    assert whole_mean.value_n == pytest.approx(2160.0)
    assert braking_peak.value_n == pytest.approx(3300.0)
    assert propulsion_mean.value_n == pytest.approx(4075.0)
    assert whole_peak.support.kind is CMJMetricSupportKind.WHOLE_MOVEMENT
    assert braking_peak.support.phase_occurrence == phases[1]
    assert whole_peak.observation.identity.semantic.metric_definition != (
        whole_mean.observation.identity.semantic.metric_definition
    )


def test_force_metrics_refuse_wrong_phase_force_quantity_and_vendor_label() -> None:
    _, _, total, _, phases, onset, takeoff, _ = _bilateral_fixture()
    wrong_phase = calculate_cmj_phase_force_metric(
        total,
        phases[2],
        CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE,
    )
    assert isinstance(wrong_phase, RefusalResult)
    assert RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED in wrong_phase.reason_codes

    weight = estimate_system_weight(
        total,
        WeighingSegment(
            total.signal.signal_id,
            total.source_artifact.artifact_id,
            total.observation.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)
    net = derive_net_vertical_force(total, weight, _mechanics_contract())
    assert not isinstance(net, RefusalResult)
    wrong_quantity = calculate_cmj_force_metric(
        net,  # type: ignore[arg-type]
        CMJForceMetric.WHOLE_MOVEMENT_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE,
        movement_onset=onset,
        takeoff=takeoff,
    )
    assert isinstance(wrong_quantity, RefusalResult)
    assert RefusalReasonCode.SIGNAL_SEMANTICS_INCOMPATIBLE in wrong_quantity.reason_codes

    vendor_label = calculate_cmj_force_metric(
        total,
        "peak force",  # type: ignore[arg-type]
        movement_onset=onset,
        takeoff=takeoff,
    )
    assert isinstance(vendor_label, RefusalResult)
    assert RefusalReasonCode.NO_REGISTERED_OPERATION in vendor_label.reason_codes


def test_force_time_mean_uses_irregular_recorded_timebase() -> None:
    times = (0.0, 0.001, 0.002, 0.004, 0.007, 0.011, 0.016, 0.022, 0.029, 0.037)
    _, _, total, _, _, onset, takeoff, _ = _bilateral_fixture(timebase=ExplicitTimebase(times))
    result = calculate_cmj_whole_movement_time_mean_total_supported_vertical_force(
        total, onset, takeoff
    )
    assert isinstance(result, CMJForceMetricResult)
    selected = total.signal.samples[onset.sample_index : takeoff.sample_index + 1]
    expected = sum(
        0.5 * (selected[offset - 1] + selected[offset]) * (times[4 + offset] - times[3 + offset])
        for offset in range(1, len(selected))
    ) / (times[takeoff.sample_index] - times[onset.sample_index])
    assert result.value_n == pytest.approx(expected)


def test_power_metrics_are_signed_total_force_times_velocity() -> None:
    _, _, total, velocity, phases, _, _, _ = _bilateral_fixture()
    for metric in CMJPowerMetric:
        result = calculate_cmj_power_metric(total, velocity, _phase_for(metric, phases), metric)
        assert isinstance(result, CMJPowerResult), (metric, result)
        phase = _phase_for(metric, phases)
        expected_samples = tuple(
            total.signal.samples[index]
            * velocity.samples[index - velocity.series.sample_start_index]
            for index in range(phase.sample_support.start_index, phase.sample_support.end_index + 1)
        )
        if metric is CMJPowerMetric.BRAKING_PEAK_NEGATIVE_POWER:
            assert result.value_w == pytest.approx(min(expected_samples))
            assert result.value_w < 0.0
        elif metric is CMJPowerMetric.PROPULSION_PEAK_POSITIVE_POWER:
            assert result.value_w == pytest.approx(max(expected_samples))
            assert result.value_w > 0.0
        else:
            assert result.value_w == pytest.approx(
                sum(
                    0.5 * (expected_samples[offset - 1] + expected_samples[offset]) * 0.001
                    for offset in range(1, len(expected_samples))
                )
                / (phase.end_time_s - phase.start_time_s)
            )
        assert result.series.samples == expected_samples


def test_power_refuses_net_force_and_unrelated_velocity() -> None:
    _, _, total, velocity, phases, _, _, contract = _bilateral_fixture()
    metric = CMJPowerMetric.BRAKING_MEAN_SIGNED_POWER
    weight = estimate_system_weight(
        total,
        WeighingSegment(
            total.signal.signal_id,
            total.source_artifact.artifact_id,
            total.observation.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)
    net = derive_net_vertical_force(total, _adjudicate(weight), contract)
    assert not isinstance(net, RefusalResult)
    refused_force = calculate_cmj_power_metric(net, velocity, phases[1], metric)  # type: ignore[arg-type]
    assert isinstance(refused_force, RefusalResult)
    other_velocity = _bilateral_fixture(
        timebase=ExplicitTimebase(
            (0.0, 0.001, 0.002, 0.004, 0.007, 0.011, 0.016, 0.022, 0.029, 0.037)
        )
    )[3]
    refused_velocity = calculate_cmj_power_metric(total, other_velocity, phases[1], metric)
    assert isinstance(refused_velocity, RefusalResult)
    assert RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH in refused_velocity.reason_codes


def test_power_peak_and_mean_are_distinct_registered_methods() -> None:
    _, _, total, velocity, phases, _, _, _ = _bilateral_fixture()
    peak = calculate_cmj_power_metric(
        total, velocity, phases[1], CMJPowerMetric.BRAKING_PEAK_NEGATIVE_POWER
    )
    mean = calculate_cmj_power_metric(
        total, velocity, phases[1], CMJPowerMetric.BRAKING_MEAN_SIGNED_POWER
    )
    assert isinstance(peak, CMJPowerResult)
    assert isinstance(mean, CMJPowerResult)
    comparison = compare_cmj_metric_results(peak, mean, claim="peak versus mean power")
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED


def test_takeoff_velocity_is_exact_projection_and_not_recomputed() -> None:
    _, _, total, velocity, phases, _, takeoff, _ = _bilateral_fixture()
    result = project_cmj_takeoff_velocity(velocity, takeoff)
    assert isinstance(result, CMJTakeoffVelocityResult)
    local_index = takeoff.sample_index - velocity.series.sample_start_index
    assert result.value_m_per_s == velocity.samples[local_index]
    assert result.observation.identity.processing.method_parameters
    forged_observation = replace(
        result.observation,
        result=replace(result.observation.result, value=ScalarValue(123.0)),
    )
    with pytest.raises(ValueError, match="does not match"):
        CMJTakeoffVelocityResult(forged_observation, velocity, takeoff)
    assert total.observation.observation_id in velocity.series.source_observation_ids
    assert phases[2].source_velocity_series_id == velocity.series.series_id


def test_takeoff_velocity_refuses_an_event_from_another_source() -> None:
    from test_cmj_jump_height import _flight_fixture

    _, wrong_takeoff, _, _ = _flight_fixture("res65-wrong-takeoff")
    _, _, _, velocity, _, _, _, _ = _bilateral_fixture()
    refused = project_cmj_takeoff_velocity(velocity, wrong_takeoff)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in refused.reason_codes


def test_rsi_mod_preserves_numerator_estimator_identity() -> None:
    from test_cmj_jump_height import _flight_fixture

    flight_height, takeoff, _, force = _flight_fixture("res65-rsi-flight")
    baseline = estimate_system_weight(
        force,
        WeighingSegment(
            force.signal.signal_id,
            force.source_artifact.artifact_id,
            force.identity.identity_id,
            0,
            5,
        ),
    )
    assert isinstance(baseline, SystemWeightResult)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    flight_result = calculate_cmj_rsi_mod(flight_height, onset, takeoff)
    assert isinstance(flight_result, CMJRSIModResult)
    assert flight_result.value_m_per_s == pytest.approx(
        flight_height.value_m / (takeoff.event_time_s - onset.event_time_s)
    )
    assert (
        flight_result.observation.result.classification.value_origin is ValueOrigin.MODEL_ESTIMATE
    )
    assert from_canonical_json(canonical_json(flight_result), CMJRSIModResult) == flight_result

    _, _, _, velocity, _, onset_bilateral, takeoff_bilateral, _ = _bilateral_fixture()
    velocity_height = estimate_takeoff_velocity_jump_height(
        velocity, takeoff_bilateral, _local_gravity("res65-bilateral")
    )
    assert not isinstance(velocity_height, RefusalResult)
    velocity_result = calculate_cmj_rsi_mod(velocity_height, onset_bilateral, takeoff_bilateral)
    assert isinstance(velocity_result, CMJRSIModResult)
    assert flight_result.observation.identity.semantic.metric_definition != (
        velocity_result.observation.identity.semantic.metric_definition
    )
    assert flight_result.numerator.value != velocity_result.numerator.value


def test_rsi_mod_refuses_wrong_events_and_free_duration() -> None:
    from test_cmj_jump_height import _flight_fixture

    jump_height, takeoff, _, force = _flight_fixture("res65-rsi-events")
    baseline = estimate_system_weight(
        force,
        WeighingSegment(
            force.signal.signal_id,
            force.source_artifact.artifact_id,
            force.identity.identity_id,
            0,
            5,
        ),
    )
    assert isinstance(baseline, SystemWeightResult)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    wrong_onset = _bilateral_fixture()[5]
    refused = calculate_cmj_rsi_mod(jump_height, wrong_onset, takeoff)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in refused.reason_codes
    with pytest.raises(TypeError):
        calculate_cmj_rsi_mod(jump_height, onset, takeoff, duration_s=1.0)  # type: ignore[call-arg]


def test_rfd_is_explicitly_deferred() -> None:
    from dynamislm.measurement.cmj import refuse_unregistered_cmj_rfd

    refusal = refuse_unregistered_cmj_rfd()
    assert isinstance(refusal, RefusalResult)
    assert refusal.refusal_class.value == "COMPUTATION_NOT_REGISTERED"
    assert RefusalReasonCode.NO_REGISTERED_OPERATION in refusal.reason_codes


def test_bilateral_asymmetry_uses_exact_channels_and_registered_equation() -> None:
    left, right, total, _, phases, _, _, _ = _bilateral_fixture()
    results: list[CMJForceAsymmetryResult] = []
    for metric in CMJAsymmetryMetric:
        result = calculate_cmj_force_asymmetry(
            left,
            right,
            _phase_for(metric, phases),
            metric,
            total_force=total,
        )
        assert isinstance(result, CMJForceAsymmetryResult), (metric, result)
        results.append(result)
        assert result.value_percent == pytest.approx(
            100.0 * (result.right_value_n - result.left_value_n) / result.left_value_n
        )
        assert result.observation.result.unit is not None
        assert result.observation.identity.processing.normalization is None
    assert results[0].observation.identity.semantic.metric_definition != (
        results[1].observation.identity.semantic.metric_definition
    )


def test_asymmetry_refuses_precombined_missing_channels_cross_trial_and_equation() -> None:
    left, right, total, _, phases, _, _, _ = _bilateral_fixture()
    refused_precombined = calculate_cmj_force_asymmetry(
        left,
        left,
        phases[1],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
    )
    assert isinstance(refused_precombined, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE in refused_precombined.reason_codes

    other_right = _rebind_samples(
        right,
        (400.0, 400.0, 400.0, 400.0, 350.0, 200.0, 250.0, 1700.0, 3300.0, 0.0),
    )
    other_trial_id = other_right.observation.context.trial_id
    assert other_trial_id is not None
    other_right = replace(
        other_right,
        observation=replace(
            other_right.observation,
            context=replace(
                other_right.observation.context,
                trial_id=replace(other_trial_id, value="different"),
            ),
        ),
    )
    refused_trial = calculate_cmj_force_asymmetry(
        left,
        other_right,
        phases[1],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
    )
    assert isinstance(refused_trial, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE in refused_trial.reason_codes

    refused_equation = calculate_cmj_force_asymmetry(
        left,
        right,
        phases[1],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
        total_force=total,
        equation="unsupported",  # type: ignore[arg-type]
    )
    assert isinstance(refused_equation, RefusalResult)
    assert RefusalReasonCode.NO_REGISTERED_OPERATION in refused_equation.reason_codes

    broken_identity = replace(
        left.identity,
        acquisition=replace(left.identity.acquisition, channel=None),
    )
    broken_left = replace(
        left,
        identity=broken_identity,
        observation=replace(left.observation, identity=broken_identity),
    )
    refused_channel = calculate_cmj_force_asymmetry(
        broken_left,
        right,
        phases[1],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
    )
    assert isinstance(refused_channel, RefusalResult)
    assert RefusalReasonCode.CHANNEL_IDENTITY_MISSING in refused_channel.reason_codes

    refused_phase = calculate_cmj_force_asymmetry(
        left,
        right,
        phases[2],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
        total_force=total,
    )
    assert isinstance(refused_phase, RefusalResult)
    assert RefusalReasonCode.PHASE_METRIC_NOT_REGISTERED in refused_phase.reason_codes


def test_metric_comparability_keeps_peak_mean_power_and_rsi_methods_distinct() -> None:
    left, right, total, velocity, phases, onset, takeoff, _ = _bilateral_fixture()
    peak = calculate_cmj_phase_force_metric(
        total, phases[1], CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE
    )
    mean = calculate_cmj_phase_force_metric(
        total, phases[1], CMJForceMetric.BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE
    )
    assert isinstance(peak, CMJForceMetricResult)
    assert isinstance(mean, CMJForceMetricResult)
    force_comparison = compare_cmj_metric_results(peak, mean, claim="same force metric")
    assert force_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    altered_boundary = replace(
        phases[1].start_boundary,
        tie_policy="an alternative tie policy is not RES-39 V1",
    )
    altered_phase = replace(phases[1], start_boundary=altered_boundary)
    altered_peak = calculate_cmj_phase_force_metric(
        total,
        altered_phase,
        CMJForceMetric.BRAKING_PEAK_TOTAL_SUPPORTED_VERTICAL_FORCE,
        output_observation_id=InstanceIdentifier("observation", "res65-altered-phase"),
    )
    assert isinstance(altered_peak, CMJForceMetricResult)
    altered_comparison = compare_cmj_metric_results(
        peak, altered_peak, claim="phase boundary method mismatch"
    )
    assert altered_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED

    power = calculate_cmj_power_metric(
        total, velocity, phases[1], CMJPowerMetric.BRAKING_MEAN_SIGNED_POWER
    )
    assert isinstance(power, CMJPowerResult)
    power_two = calculate_cmj_power_metric(
        total,
        velocity,
        phases[1],
        CMJPowerMetric.BRAKING_MEAN_SIGNED_POWER,
        output_observation_id=InstanceIdentifier("observation", "res65-power-two"),
    )
    assert isinstance(power_two, CMJPowerResult)
    assert (
        compare_cmj_metric_results(power, power_two, claim="same power metric").state
        is ComparabilityState.COMPARABLE
    )
    asymmetry = calculate_cmj_force_asymmetry(
        left,
        right,
        phases[1],
        CMJAsymmetryMetric.BRAKING_PEAK_FORCE,
        total_force=total,
    )
    assert isinstance(asymmetry, CMJForceAsymmetryResult)
    cross_comparison = compare_cmj_metric_results(peak, asymmetry, claim="force versus asymmetry")
    assert cross_comparison.state is ComparabilityState.NOT_COMPARABLE
    assert onset.sample_index < takeoff.sample_index


def test_res40_session_aggregation_accepts_res65_scalar_metric_results() -> None:
    _, _, total, _, phases, _, _, _ = _bilateral_fixture()
    first = calculate_cmj_phase_force_metric(
        total,
        phases[1],
        CMJForceMetric.BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE,
        output_observation_id=InstanceIdentifier("observation", "res65-session-a"),
    )
    second = calculate_cmj_phase_force_metric(
        total,
        phases[1],
        CMJForceMetric.BRAKING_TIME_MEAN_TOTAL_SUPPORTED_VERTICAL_FORCE,
        output_observation_id=InstanceIdentifier("observation", "res65-session-b"),
    )
    assert isinstance(first, CMJForceMetricResult)
    assert isinstance(second, CMJForceMetricResult)
    context = replace(
        first.observation.context,
        athlete_id=InstanceIdentifier("athlete", "res65-session-athlete"),
        session_id=InstanceIdentifier("session", "res65-session"),
        test_instance_id=InstanceIdentifier("test-instance", "res65-test"),
        trial_id=InstanceIdentifier("trial", "a"),
    )
    first = CMJForceMetricResult(
        replace(first.observation, context=context), first.metric, first.source_force, first.support
    )
    second_context = replace(context, trial_id=InstanceIdentifier("trial", "b"))
    second = CMJForceMetricResult(
        replace(second.observation, context=second_context),
        second.metric,
        second.source_force,
        second.support,
    )
    candidate_set = DeclaredCandidateTrialSet(
        InstanceIdentifier("athlete", "res65-session-athlete"),
        InstanceIdentifier("session", "res65-session"),
        first.observation.identity.semantic.test_family,
        (InstanceIdentifier("trial", "a"), InstanceIdentifier("trial", "b")),
        (first.observation.observation_id, second.observation.observation_id),
    )
    eligibility = evaluate_trial_eligibility(candidate_set, (first, second))
    assert not isinstance(eligibility, RefusalResult)
    selection = select_trials(candidate_set, eligibility)
    assert isinstance(selection, TrialSelectionDecision)
    summary = aggregate_cmj_session(selection, (first, second))
    assert not isinstance(summary, RefusalResult)
    assert summary.value == pytest.approx(first.value_n)
    assert summary.selection_rule == CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1


def test_new_metric_results_roundtrip_and_reject_forged_values() -> None:
    left, right, total, velocity, phases, onset, takeoff, _ = _bilateral_fixture()
    force_result = calculate_cmj_whole_movement_peak_total_supported_vertical_force(
        total, onset, takeoff
    )
    power_result = calculate_cmj_power_metric(
        total, velocity, phases[2], CMJPowerMetric.PROPULSION_MEAN_SIGNED_POWER
    )
    asymmetry_result = calculate_cmj_force_asymmetry(
        left,
        right,
        phases[2],
        CMJAsymmetryMetric.PROPULSION_TIME_MEAN_FORCE,
        total_force=total,
    )
    for result in (force_result, power_result, asymmetry_result):
        assert not isinstance(result, RefusalResult)
        restored = from_canonical_json(canonical_json(result), type(result))
        assert restored == result
        assert canonical_hash(restored) == canonical_hash(result)
    assert isinstance(force_result, CMJForceMetricResult)
    forged_observation = replace(
        force_result.observation,
        result=replace(force_result.observation.result, value=ScalarValue(999999.0)),
    )
    with pytest.raises(ValueError, match="does not match"):
        CMJForceMetricResult(
            forged_observation,
            force_result.metric,
            force_result.source_force,
            force_result.support,
        )
