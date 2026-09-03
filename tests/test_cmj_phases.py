from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    ValueOrigin,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import ComparabilityReasonCode, ComparabilityState
from dynamislm.measurement.cmj import (
    CMJ_BRAKING_PHASE_DEFINITION,
    CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_SPEC,
    CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1,
    CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY,
    CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION,
    CMJ_PROPULSION_PHASE_DEFINITION,
    CMJ_UNWEIGHTING_PHASE_DEFINITION,
    CMJEventOccurrence,
    CMJIntegrationInterval,
    CMJPhaseBoundary,
    CMJPhaseBoundaryKind,
    CMJPhaseLabel,
    CMJPhaseMetricResult,
    CMJPhaseOccurrence,
    CMJPhaseSystem,
    CMJThresholdDirection,
    DisplacementOrigin,
    NetVerticalForceResult,
    QualifiedZeroVelocityReference,
    SupportedSystemComRelativeDisplacementResult,
    SupportedSystemComVelocityResult,
    calculate_cmj_phase_duration,
    calculate_cmj_phase_net_vertical_impulse,
    calculate_cmj_phase_relative_displacement_change,
    compare_cmj_phase_metrics,
    construct_cmj_phase_occurrences,
    derive_net_vertical_force,
    derive_physical_system_mass,
    derive_supported_system_com_acceleration,
    derive_supported_system_com_relative_vertical_displacement,
    derive_supported_system_com_velocity,
    detect_movement_onset,
    detect_peak_negative_supported_system_com_velocity,
    detect_takeoff,
    integrate_net_vertical_impulse,
    refusal_for_cmj_phase_comparability,
)
from dynamislm.measurement.cmj.signal import ExplicitTimebase, SignalTimebase
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    ScientificIdentifier,
)
from dynamislm.refusal import RefusalReasonCode, RefusalResult
from test_cmj import (
    _absolute_parameters,
    _local_gravity,
    _mechanics_fixture,
    _onset_parameters,
)

_UNIQUE_TRACE = (100.0, 100.0, 100.0, 100.0, -900.0, -900.0, -400.0, 2600.0, 5100.0, 0.0)
_TIED_TRACE = (100.0, 100.0, 100.0, 100.0, -900.0, -900.0, 1100.0, 2100.0, 1100.0, 0.0)
_SUBTHRESHOLD_TRACE = (100.0, 100.0, 100.0, 100.0, 90.0, 90.0, 100.0, 151.0, 151.0, 0.0)
_ZERO_LENGTH_TRACE = (100.0, 100.0, 100.0, 100.0, 0.0, 300.0, 100.0, 100.0, 5100.0, 0.0)


def _phase_inputs(
    suffix: str,
    samples: tuple[float, ...] = _UNIQUE_TRACE,
    *,
    timebase: SignalTimebase | None = None,
    external_loading: str = "none",
) -> tuple[
    SupportedSystemComVelocityResult,
    NetVerticalForceResult,
    SupportedSystemComRelativeDisplacementResult,
    CMJEventOccurrence,
    CMJEventOccurrence,
]:
    source, total, weight, contract = _mechanics_fixture(
        suffix,
        samples,
        timebase=timebase,
        external_loading=external_loading,
        weighing_end_index=3,
    )
    onset = detect_movement_onset(
        source,
        weight,
        _onset_parameters(weight, search_start_index=4, dwell_samples=1),
    )
    assert not isinstance(onset, RefusalResult)
    takeoff = detect_takeoff(
        total,
        _absolute_parameters(
            20.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=1,
            search_start_index=9,
        ),
        onset=onset,
    )
    assert not isinstance(takeoff, RefusalResult)
    mass = derive_physical_system_mass(weight, _local_gravity("res39-synthetic"))
    assert not isinstance(mass, RefusalResult)
    net_force = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net_force, NetVerticalForceResult)
    acceleration = derive_supported_system_com_acceleration(net_force, mass, contract)
    assert not isinstance(acceleration, RefusalResult)
    velocity = derive_supported_system_com_velocity(
        acceleration,
        CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 9),
        QualifiedZeroVelocityReference.from_system_weight(weight, 2),
    )
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    displacement = derive_supported_system_com_relative_vertical_displacement(
        velocity,
        DisplacementOrigin.zero_at_velocity_start(velocity.series.series_id, 2),
    )
    assert isinstance(displacement, SupportedSystemComRelativeDisplacementResult)
    return velocity, net_force, displacement, onset, takeoff


def _phase_fixture(
    suffix: str,
    samples: tuple[float, ...] = _UNIQUE_TRACE,
    *,
    timebase: SignalTimebase | None = None,
    external_loading: str = "none",
) -> tuple[
    SupportedSystemComVelocityResult,
    NetVerticalForceResult,
    SupportedSystemComRelativeDisplacementResult,
    tuple[CMJPhaseOccurrence, ...],
    CMJEventOccurrence,
    CMJEventOccurrence,
]:
    velocity, net_force, displacement, onset, takeoff = _phase_inputs(
        suffix,
        samples,
        timebase=timebase,
        external_loading=external_loading,
    )
    phases = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert not isinstance(phases, RefusalResult)
    return velocity, net_force, displacement, phases, onset, takeoff


def _metric(value: CMJPhaseMetricResult | RefusalResult) -> CMJPhaseMetricResult:
    assert isinstance(value, CMJPhaseMetricResult)
    return value


def test_res39_phase_system_is_versioned_and_labels_are_not_global_aliases() -> None:
    assert SERIALIZATION_VERSION == 3
    assert isinstance(CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_SPEC, CMJPhaseSystem)
    assert CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.identifier.version == "1.0.0"
    assert CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1.identifier.object_type == "phase-system"
    assert tuple(CMJPhaseLabel) == (
        CMJPhaseLabel.UNWEIGHTING,
        CMJPhaseLabel.BRAKING,
        CMJPhaseLabel.PROPULSION,
    )
    assert "ECCENTRIC" not in CMJPhaseLabel.__members__
    assert "CONCENTRIC" not in CMJPhaseLabel.__members__
    assert "YIELDING" not in CMJPhaseLabel.__members__
    assert str(CMJPhaseLabel.BRAKING.value) != "ECCENTRIC"
    assert str(CMJPhaseLabel.PROPULSION.value) != "CONCENTRIC"
    assert str(CMJPhaseLabel.UNWEIGHTING.value) != "YIELDING"


def test_res39_unregistered_alternative_phase_system_is_not_silently_aliased() -> None:
    velocity, _, _, phases, onset, takeoff = _phase_fixture("phase-alternative-system")
    alternative = RegistryReference(
        ScientificIdentifier("literature", "phase-system", "harry-joint-power", "1.0.0"),
        "Harry joint-power-informed phase system",
    )
    refusal = detect_peak_negative_supported_system_com_velocity(
        velocity,
        onset,
        takeoff,
        phase_system=alternative,
    )
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.PHASE_SYSTEM_NOT_REGISTERED in refusal.reason_codes
    assert phases[1].label is CMJPhaseLabel.BRAKING


def test_res39_peak_negative_velocity_is_unique_and_tie_policy_is_earliest() -> None:
    velocity, _, _, phases, _, _ = _phase_fixture("phase-unique")
    peak = phases[0].end_boundary
    assert peak.kind is CMJPhaseBoundaryKind.PEAK_NEGATIVE_SUPPORTED_SYSTEM_COM_VELOCITY
    assert peak.sample_index == 6
    assert peak.tie_policy == "earliest source sample among tied minimum velocity values"
    assert peak.interpolation_policy == "none; exact source sample only"

    tied_velocity, _, _, tied_phases, tied_onset, tied_takeoff = _phase_fixture(
        "phase-tied", _TIED_TRACE
    )
    tied_peak = tied_phases[0].end_boundary
    assert tied_peak.sample_index == 5
    assert tied_velocity.series.samples[3] == tied_velocity.series.samples[4]
    repeated_peak = detect_peak_negative_supported_system_com_velocity(
        tied_velocity, tied_onset, tied_takeoff
    )
    assert isinstance(repeated_peak, CMJPhaseBoundary)
    assert canonical_json(repeated_peak) == canonical_json(tied_peak)


def test_res39_direction_change_is_first_positive_sample_without_hidden_threshold() -> None:
    _, _, _, exact_zero_phases, _, _ = _phase_fixture("phase-exact-zero", _TIED_TRACE)
    exact_zero = exact_zero_phases[1].end_boundary
    assert exact_zero.sample_index == 8
    assert exact_zero_phases[1].start_boundary.sample_index == 5
    assert exact_zero.interpolation_policy == "none; discrete transition gap retained"
    assert exact_zero.velocity_threshold_policy == "none; strict velocity > 0.0 m/s"

    _, _, _, subthreshold_phases, _, _ = _phase_fixture("phase-subthreshold", _SUBTHRESHOLD_TRACE)
    subthreshold = subthreshold_phases[1].end_boundary
    assert subthreshold.sample_index == 7
    assert 0.0 < subthreshold.velocity_m_per_s < 0.01

    _, _, _, crossing_phases, _, _ = _phase_fixture("phase-crossing", _UNIQUE_TRACE)
    crossing = crossing_phases[1].end_boundary
    assert crossing.sample_index == 8
    assert crossing_phases[1].start_boundary.sample_index == 6
    assert crossing.velocity_m_per_s > 0.0


def test_res39_unresolved_direction_refuses_only_phase_construction() -> None:
    source, total, weight, contract = _mechanics_fixture(
        "phase-no-direction",
        (100.0, 100.0, 100.0, 100.0, -900.0, -900.0, -900.0, -900.0, -900.0, 0.0),
        weighing_end_index=3,
    )
    onset = detect_movement_onset(
        source, weight, _onset_parameters(weight, search_start_index=4, dwell_samples=1)
    )
    assert not isinstance(onset, RefusalResult)
    takeoff = detect_takeoff(
        total,
        _absolute_parameters(
            20.0, CMJThresholdDirection.BELOW_THRESHOLD, dwell_samples=1, search_start_index=9
        ),
        onset=onset,
    )
    assert not isinstance(takeoff, RefusalResult)
    mass = derive_physical_system_mass(weight, _local_gravity("phase-no-direction"))
    assert not isinstance(mass, RefusalResult)
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert not isinstance(acceleration, RefusalResult)
    velocity = derive_supported_system_com_velocity(
        acceleration,
        CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 9),
        QualifiedZeroVelocityReference.from_system_weight(weight, 2),
    )
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    refusal = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.DIRECTION_CHANGE_UNRESOLVED in refusal.reason_codes
    assert RefusalReasonCode.PROPULSION_ONSET_UNRESOLVED in refusal.reason_codes
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    assert isinstance(net, NetVerticalForceResult)


def test_res39_zero_length_phase_refuses_granularly() -> None:
    velocity, net, _, onset, takeoff = _phase_inputs("phase-zero-length", _ZERO_LENGTH_TRACE)
    refusal = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.PHASE_INTERVAL_INVALID in refusal.reason_codes
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    assert isinstance(net, NetVerticalForceResult)


def test_res39_wrong_velocity_and_wrong_event_sources_are_refused() -> None:
    first_velocity, _, _, _, first_onset, first_takeoff = _phase_fixture("phase-source-first")
    second_velocity, _, _, _, second_onset, second_takeoff = _phase_fixture("phase-source-second")

    wrong_velocity = construct_cmj_phase_occurrences(second_velocity, first_onset, first_takeoff)
    assert isinstance(wrong_velocity, RefusalResult)
    assert RefusalReasonCode.PHASE_SOURCE_MISMATCH in wrong_velocity.reason_codes

    wrong_events = construct_cmj_phase_occurrences(first_velocity, second_onset, first_takeoff)
    assert isinstance(wrong_events, RefusalResult)
    assert RefusalReasonCode.PHASE_SOURCE_MISMATCH in wrong_events.reason_codes


def test_res39_occurrences_preserve_phase_identity_boundaries_and_provenance() -> None:
    velocity, _, _, phases, _, _ = _phase_fixture("phase-occurrence")
    assert tuple(phase.label for phase in phases) == (
        CMJPhaseLabel.UNWEIGHTING,
        CMJPhaseLabel.BRAKING,
        CMJPhaseLabel.PROPULSION,
    )
    assert len({phase.occurrence_id for phase in phases}) == 3
    for phase in phases:
        assert phase.phase_system == CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1
        assert phase.source_velocity_series_id == velocity.series.series_id
        assert phase.source_velocity_observation_id == velocity.observation.observation_id
        assert phase.sample_support.convention == CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION
        assert phase.boundary_convention == CMJ_PHASE_SHARED_SAMPLE_BOUNDARY_CONVENTION
        assert phase.start_time_s == phase.start_boundary.boundary_time_s
        assert phase.end_time_s == phase.end_boundary.boundary_time_s
        runs = tuple(
            run
            for run in phase.provenance.processing_runs
            if run.output_entity_id == phase.occurrence_id
        )
        assert len(runs) == 1
        assert runs[0].method == CMJ_FORCE_COM_VELOCITY_PHASE_SYSTEM_V1
        assert phase.evidence_decision.identifier.object_type == "decision-record"
    assert phases[0].phase_definition == CMJ_UNWEIGHTING_PHASE_DEFINITION
    assert phases[1].phase_definition == CMJ_BRAKING_PHASE_DEFINITION
    assert phases[2].phase_definition == CMJ_PROPULSION_PHASE_DEFINITION
    assert phases[1].end_boundary.sample_index == phases[2].start_boundary.sample_index
    assert phases[1].end_boundary.kind is CMJPhaseBoundaryKind.DIRECTION_CHANGE
    assert phases[2].start_boundary.kind is CMJPhaseBoundaryKind.PROPULSION_ONSET
    assert phases[1].end_boundary.boundary_id != phases[2].start_boundary.boundary_id


def test_res39_durations_use_boundary_times_and_irregular_timestamps() -> None:
    _, _, _, regular_phases, _, _ = _phase_fixture("phase-duration-regular")
    assert _metric(calculate_cmj_phase_duration(regular_phases[0])).value == pytest.approx(0.002)
    assert _metric(calculate_cmj_phase_duration(regular_phases[1])).value == pytest.approx(0.002)
    assert _metric(calculate_cmj_phase_duration(regular_phases[2])).value == pytest.approx(0.001)

    explicit_times = (10.0, 10.001, 10.003, 10.006, 10.010, 10.015, 10.021, 10.028, 10.036, 10.045)
    _, _, _, explicit_phases, _, _ = _phase_fixture(
        "phase-duration-explicit",
        timebase=ExplicitTimebase(explicit_times),
    )
    assert _metric(calculate_cmj_phase_duration(explicit_phases[0])).value == pytest.approx(0.011)
    assert _metric(calculate_cmj_phase_duration(explicit_phases[1])).value == pytest.approx(0.015)
    assert _metric(calculate_cmj_phase_duration(explicit_phases[2])).value == pytest.approx(0.009)


def test_res39_impulses_reuse_res37_trapezoids_and_do_not_double_count_shared_samples() -> None:
    _, net_force, _, phases, _, _ = _phase_fixture("phase-impulse")
    braking = _metric(calculate_cmj_phase_net_vertical_impulse(phases[1], net_force))
    propulsion = _metric(calculate_cmj_phase_net_vertical_impulse(phases[2], net_force))
    assert braking.value == pytest.approx(4.75)
    assert propulsion.value == pytest.approx(2.45)
    assert braking.source_integration_interval is not None
    assert braking.source_integration_interval.boundary_convention == (
        CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY
    )
    combined = integrate_net_vertical_impulse(
        net_force,
        CMJIntegrationInterval.explicit_sample(net_force.series.series_id, 6, 9),
    )
    assert not isinstance(combined, RefusalResult)
    assert combined.value_ns == pytest.approx(braking.value + propulsion.value)


def test_res39_displacement_changes_are_supported_system_relative_deltas() -> None:
    _, _, displacement, phases, _, _ = _phase_fixture("phase-displacement")
    braking = _metric(calculate_cmj_phase_relative_displacement_change(phases[1], displacement))
    propulsion = _metric(calculate_cmj_phase_relative_displacement_change(phases[2], displacement))
    assert braking.value == pytest.approx(
        displacement.series.samples[8 - displacement.series.sample_start_index]
        - displacement.series.samples[6 - displacement.series.sample_start_index]
    )
    assert propulsion.value == pytest.approx(
        displacement.series.samples[9 - displacement.series.sample_start_index]
        - displacement.series.samples[8 - displacement.series.sample_start_index]
    )
    assert (
        braking.observation.result.classification.value_origin
        is ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    )
    assert (
        "athlete-only" not in braking.observation.identity.semantic.construct.display_label.lower()
    )


def test_res39_loaded_fixture_retains_supported_system_contract() -> None:
    velocity, net_force, displacement, phases, _, _ = _phase_fixture(
        "phase-loaded",
        external_loading="stable-attached-supported-load",
    )
    assert phases[0].source_system_contract.includes_supported_external_load
    assert (
        phases[0].source_system_contract.system_description
        == "athlete plus supported external load"
    )
    assert all(phase.source_system_contract == phases[0].source_system_contract for phase in phases)
    for result in (
        calculate_cmj_phase_net_vertical_impulse(phases[1], net_force),
        calculate_cmj_phase_relative_displacement_change(phases[2], displacement),
    ):
        result = _metric(result)
        assert result.source_system_contract.includes_supported_external_load
        assert result.observation.identity.semantic.construct.display_label.lower().startswith(
            "cmj supported"
        )
    assert velocity.system_contract.includes_supported_external_load


def test_res39_phase_and_metric_serialization_are_deterministic() -> None:
    _, net_force, _, phases, _, _ = _phase_fixture("phase-serialization")
    phase = phases[1]
    metric = _metric(calculate_cmj_phase_net_vertical_impulse(phase, net_force))
    restored_phase = from_canonical_json(canonical_json(phase), CMJPhaseOccurrence)
    restored_metric = from_canonical_json(canonical_json(metric), CMJPhaseMetricResult)
    assert canonical_json(restored_phase) == canonical_json(phase)
    assert canonical_hash(restored_phase) == canonical_hash(phase)
    assert canonical_json(restored_metric) == canonical_json(metric)
    assert canonical_hash(restored_metric) == canonical_hash(metric)


def test_res39_same_label_comparison_requires_registered_source_method_identity() -> None:
    _, first_net, _, first_phases, _, _ = _phase_fixture("phase-compare-first")
    _, second_net, _, second_phases, _, _ = _phase_fixture("phase-compare-second")
    first = _metric(calculate_cmj_phase_net_vertical_impulse(first_phases[1], first_net))
    second = _metric(calculate_cmj_phase_net_vertical_impulse(second_phases[1], second_net))
    comparison = compare_cmj_phase_metrics(
        first,
        second,
        claim="compare V1 braking net vertical impulse",
        request_id=InstanceIdentifier("comparability-request", "phase-same-label"),
    )
    assert comparison.state is ComparabilityState.COMPARABLE

    changed_phase = replace(
        second_phases[1],
        end_boundary=replace(
            second_phases[1].end_boundary,
            velocity_threshold_policy="registered positive threshold > 0.01 m/s",
        ),
    )
    changed = replace(second, phase_occurrence=changed_phase)
    changed_comparison = compare_cmj_phase_metrics(
        first,
        changed,
        claim="compare V1 braking net vertical impulse with a changed boundary rule",
        request_id=InstanceIdentifier("comparability-request", "phase-method-change"),
    )
    assert changed_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in (changed_comparison.reason_codes)

    changed_velocity_phase = replace(
        second_phases[1],
        source_velocity_integration_interval=replace(
            second_phases[1].source_velocity_integration_interval,
            end_index=8,
        ),
    )
    changed_velocity = replace(second, phase_occurrence=changed_velocity_phase)
    changed_velocity_comparison = compare_cmj_phase_metrics(
        first,
        changed_velocity,
        claim="compare V1 braking net vertical impulse with a changed velocity interval",
        request_id=InstanceIdentifier("comparability-request", "phase-velocity-interval-change"),
    )
    assert changed_velocity_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in (
        changed_velocity_comparison.reason_codes
    )
    refused = refusal_for_cmj_phase_comparability(
        changed_comparison,
        blocked_claim="compare V1 braking net vertical impulse",
        observation_ids=(first.observation.observation_id, changed.observation.observation_id),
    )
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.PHASE_COMPARABILITY_UNESTABLISHED in refused.reason_codes
    assert refused.observation_ids == (
        first.observation.observation_id,
        changed.observation.observation_id,
    )


def test_res39_wrong_metric_source_refuses_without_erasing_valid_phase() -> None:
    _, first_net, _, first_phases, _, _ = _phase_fixture("phase-metric-source-first")
    _, second_net, _, _, _, _ = _phase_fixture("phase-metric-source-second")
    refusal = calculate_cmj_phase_net_vertical_impulse(first_phases[1], second_net)
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.PHASE_SOURCE_MISMATCH in refusal.reason_codes
    assert first_phases[1].label is CMJPhaseLabel.BRAKING
    assert isinstance(first_net, NetVerticalForceResult)


def test_res39_metric_source_binds_exact_upstream_mechanics_lineage() -> None:
    velocity, _, _, onset, takeoff = _phase_inputs("phase-exact-lineage")
    phases = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert not isinstance(phases, RefusalResult)

    _, total, alternate_weight, contract = _mechanics_fixture(
        "phase-exact-lineage",
        _UNIQUE_TRACE,
        weighing_end_index=2,
    )
    alternate_net = derive_net_vertical_force(total, alternate_weight, contract)
    assert isinstance(alternate_net, NetVerticalForceResult)
    net_refusal = calculate_cmj_phase_net_vertical_impulse(phases[1], alternate_net)
    assert isinstance(net_refusal, RefusalResult)
    assert RefusalReasonCode.PHASE_SOURCE_MISMATCH in net_refusal.reason_codes

    _, total, weight, contract = _mechanics_fixture(
        "phase-exact-lineage",
        _UNIQUE_TRACE,
        weighing_end_index=3,
    )
    mass = derive_physical_system_mass(weight, _local_gravity("res39-synthetic"))
    assert not isinstance(mass, RefusalResult)
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert not isinstance(acceleration, RefusalResult)
    alternate_velocity = derive_supported_system_com_velocity(
        acceleration,
        CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 1, 9),
        QualifiedZeroVelocityReference.from_system_weight(weight, 1),
    )
    assert isinstance(alternate_velocity, SupportedSystemComVelocityResult)
    alternate_displacement = derive_supported_system_com_relative_vertical_displacement(
        alternate_velocity,
        DisplacementOrigin.zero_at_velocity_start(alternate_velocity.series.series_id, 1),
    )
    assert isinstance(alternate_displacement, SupportedSystemComRelativeDisplacementResult)
    displacement_refusal = calculate_cmj_phase_relative_displacement_change(
        phases[2], alternate_displacement
    )
    assert isinstance(displacement_refusal, RefusalResult)
    assert RefusalReasonCode.PHASE_SOURCE_MISMATCH in displacement_refusal.reason_codes
