from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    MetadataEntry,
    ValueOrigin,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import ComparabilityReasonCode, ComparabilityResult, ComparabilityState
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
    CMJPhaseMetric,
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
from dynamislm.measurement.cmj.signal import ExplicitTimebase, RegularTimebase, SignalTimebase
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
_RES49_FIRST_TRACE = (100.0, 100.0, 100.0, 100.0, -900.0, -900.0, -400.0, 6100.0, 0.0, 0.0)
_RES49_SECOND_TRACE = (100.0, 100.0, 100.0, 100.0, 100.0, -900.0, -400.0, -900.0, 6100.0, 0.0)
_RES49_VALUE_TRACE = (100.0, 100.0, 100.0, 100.0, 100.0, -900.0, -300.0, -900.0, 6200.0, 0.0)
_RES49_QC_TRACE = (101.0, 99.0, 100.0, 100.0, -900.0, -900.0, -400.0, 6100.0, 0.0, 0.0)

type PhaseFixture = tuple[
    SupportedSystemComVelocityResult,
    NetVerticalForceResult,
    SupportedSystemComRelativeDisplacementResult,
    tuple[CMJPhaseOccurrence, ...],
    CMJEventOccurrence,
    CMJEventOccurrence,
]


def _phase_inputs(
    suffix: str,
    samples: tuple[float, ...] = _UNIQUE_TRACE,
    *,
    timebase: SignalTimebase | None = None,
    external_loading: str = "none",
    weighing_start_index: int = 0,
    weighing_end_index: int = 3,
    onset_search_start_index: int = 4,
    takeoff_search_start_index: int = 9,
    onset_sigma_multiplier: float | None = None,
    onset_dwell_samples: int = 1,
    takeoff_threshold_n: float = 20.0,
    takeoff_dwell_samples: int = 1,
    velocity_start_index: int = 2,
    velocity_end_index: int = 9,
    zero_reference_sample_index: int | None = None,
    weighing_selection_parameters: tuple[MetadataEntry, ...] = (),
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
        weighing_start_index=weighing_start_index,
        weighing_end_index=weighing_end_index,
        weighing_selection_parameters=weighing_selection_parameters,
    )
    onset_parameters = _onset_parameters(
        weight, search_start_index=onset_search_start_index, dwell_samples=onset_dwell_samples
    )
    if onset_sigma_multiplier is not None:
        onset_parameters = replace(onset_parameters, sigma_multiplier=onset_sigma_multiplier)
    onset = detect_movement_onset(
        source,
        weight,
        onset_parameters,
    )
    assert not isinstance(onset, RefusalResult)
    takeoff = detect_takeoff(
        total,
        _absolute_parameters(
            takeoff_threshold_n,
            CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=takeoff_dwell_samples,
            search_start_index=takeoff_search_start_index,
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
        CMJIntegrationInterval.explicit_sample(
            acceleration.series.series_id, velocity_start_index, velocity_end_index
        ),
        QualifiedZeroVelocityReference.from_system_weight(
            weight,
            velocity_start_index
            if zero_reference_sample_index is None
            else zero_reference_sample_index,
        ),
    )
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    displacement = derive_supported_system_com_relative_vertical_displacement(
        velocity,
        DisplacementOrigin.zero_at_velocity_start(velocity.series.series_id, velocity_start_index),
    )
    assert isinstance(displacement, SupportedSystemComRelativeDisplacementResult)
    return velocity, net_force, displacement, onset, takeoff


def _phase_fixture(
    suffix: str,
    samples: tuple[float, ...] = _UNIQUE_TRACE,
    *,
    timebase: SignalTimebase | None = None,
    external_loading: str = "none",
    weighing_start_index: int = 0,
    weighing_end_index: int = 3,
    onset_search_start_index: int = 4,
    takeoff_search_start_index: int = 9,
    onset_sigma_multiplier: float | None = None,
    onset_dwell_samples: int = 1,
    takeoff_threshold_n: float = 20.0,
    takeoff_dwell_samples: int = 1,
    velocity_start_index: int = 2,
    velocity_end_index: int = 9,
    zero_reference_sample_index: int | None = None,
    weighing_selection_parameters: tuple[MetadataEntry, ...] = (),
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
        weighing_start_index=weighing_start_index,
        weighing_end_index=weighing_end_index,
        onset_search_start_index=onset_search_start_index,
        takeoff_search_start_index=takeoff_search_start_index,
        onset_sigma_multiplier=onset_sigma_multiplier,
        onset_dwell_samples=onset_dwell_samples,
        takeoff_threshold_n=takeoff_threshold_n,
        takeoff_dwell_samples=takeoff_dwell_samples,
        velocity_start_index=velocity_start_index,
        velocity_end_index=velocity_end_index,
        zero_reference_sample_index=zero_reference_sample_index,
        weighing_selection_parameters=weighing_selection_parameters,
    )
    phases = construct_cmj_phase_occurrences(velocity, onset, takeoff)
    assert not isinstance(phases, RefusalResult)
    return velocity, net_force, displacement, phases, onset, takeoff


def _metric(value: CMJPhaseMetricResult | RefusalResult) -> CMJPhaseMetricResult:
    assert isinstance(value, CMJPhaseMetricResult)
    return value


def _phase_metric(fixture: PhaseFixture, metric: CMJPhaseMetric) -> CMJPhaseMetricResult:
    _, net_force, displacement, phases, _, _ = fixture
    phase_index = 1 if metric.value.startswith("BRAKING") else 2
    phase = phases[phase_index]
    if metric.value.endswith("DURATION"):
        return _metric(calculate_cmj_phase_duration(phase))
    if metric.value.endswith("IMPULSE"):
        return _metric(calculate_cmj_phase_net_vertical_impulse(phase, net_force))
    return _metric(calculate_cmj_phase_relative_displacement_change(phase, displacement))


def _compare_phase_metrics(
    left_fixture: PhaseFixture,
    right_fixture: PhaseFixture,
    metric: CMJPhaseMetric,
    label: str,
) -> ComparabilityResult:
    return compare_cmj_phase_metrics(
        _phase_metric(left_fixture, metric),
        _phase_metric(right_fixture, metric),
        claim=label,
        request_id=InstanceIdentifier("comparability-request", f"res49-{label}"),
    )


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
    assert changed_velocity_comparison.state is ComparabilityState.COMPARABLE
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


def test_res49_reproduces_over_refusal_for_same_method_trial_coordinates() -> None:
    second_velocity, second_net, _, second_phases, second_onset, second_takeoff = _phase_fixture(
        "phase-instance-second",
        _RES49_SECOND_TRACE,
        takeoff_search_start_index=8,
    )
    first_velocity, first_net_result, _, first_phases, first_onset, first_takeoff = _phase_fixture(
        "phase-instance-first",
        _RES49_FIRST_TRACE,
        takeoff_search_start_index=8,
    )
    assert first_velocity is not second_velocity
    assert (first_onset.sample_index, first_phases[0].end_boundary.sample_index) == (4, 6)
    assert (first_phases[1].end_boundary.sample_index, first_takeoff.sample_index) == (7, 8)
    assert (second_onset.sample_index, second_phases[0].end_boundary.sample_index) == (5, 7)
    assert (second_phases[1].end_boundary.sample_index, second_takeoff.sample_index) == (8, 9)

    first_metric = _metric(
        calculate_cmj_phase_net_vertical_impulse(first_phases[1], first_net_result)
    )
    second_metric = _metric(calculate_cmj_phase_net_vertical_impulse(second_phases[1], second_net))
    comparison = compare_cmj_phase_metrics(
        first_metric,
        second_metric,
        claim="compare same-method V1 braking impulse across trial realizations",
        request_id=InstanceIdentifier("comparability-request", "phase-instance-reproduction"),
    )
    assert comparison.state is ComparabilityState.COMPARABLE


def test_res49_same_method_coordinates_and_values_are_comparable_for_all_initial_metrics() -> None:
    first = _phase_fixture("res49-method-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8)
    second = _phase_fixture("res49-method-second", _RES49_VALUE_TRACE, takeoff_search_start_index=8)
    assert tuple(
        (phase.start_boundary.sample_index, phase.end_boundary.sample_index) for phase in first[3]
    ) != tuple(
        (phase.start_boundary.sample_index, phase.end_boundary.sample_index) for phase in second[3]
    )
    for metric in CMJPhaseMetric:
        if metric is CMJPhaseMetric.UNWEIGHTING_DURATION:
            continue
        comparison = _compare_phase_metrics(first, second, metric, f"res49-{metric.value}")
        assert comparison.state is ComparabilityState.COMPARABLE

    assert (
        _phase_metric(first, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE).value
        != _phase_metric(second, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE).value
    )
    first_propulsion_impulse = _phase_metric(first, CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE)
    second_propulsion_impulse = _phase_metric(
        second, CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE
    )
    assert first_propulsion_impulse.value != second_propulsion_impulse.value


def test_res49_configured_detector_search_start_is_event_method_identity() -> None:
    first = _phase_fixture("res49-search-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8)
    movement_search_changed = _phase_fixture(
        "res49-search-second",
        _RES49_FIRST_TRACE,
        onset_search_start_index=5,
        takeoff_search_start_index=8,
    )
    takeoff_search_changed = _phase_fixture(
        "res49-search-third",
        _RES49_FIRST_TRACE,
        onset_search_start_index=4,
        takeoff_search_start_index=9,
    )

    assert first[4].detector_parameters.search_start_index == 4
    assert movement_search_changed[4].detector_parameters.search_start_index == 5
    assert (
        first[5].detector_parameters.search_start_index
        != takeoff_search_changed[5].detector_parameters.search_start_index
    )
    for label, changed in (
        ("movement-onset-search-start", movement_search_changed),
        ("takeoff-search-start", takeoff_search_changed),
    ):
        comparison = _compare_phase_metrics(
            first, changed, CMJPhaseMetric.BRAKING_DURATION, f"res49-{label}"
        )
        assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
        assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in comparison.reason_codes


def test_res49_same_method_phase_durations_can_differ() -> None:
    first = _phase_fixture("res49-duration-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8)
    longer = _phase_fixture(
        "res49-duration-longer",
        (
            100.0,
            100.0,
            100.0,
            100.0,
            -900.0,
            -900.0,
            -400.0,
            1000.0,
            1000.0,
            1000.0,
            1000.0,
            1000.0,
            0.0,
        ),
        takeoff_search_start_index=8,
        velocity_end_index=12,
    )
    assert (
        _phase_metric(first, CMJPhaseMetric.BRAKING_DURATION).value
        != _phase_metric(longer, CMJPhaseMetric.BRAKING_DURATION).value
    )
    assert (
        _phase_metric(first, CMJPhaseMetric.PROPULSION_DURATION).value
        != _phase_metric(longer, CMJPhaseMetric.PROPULSION_DURATION).value
    )
    for metric in (CMJPhaseMetric.BRAKING_DURATION, CMJPhaseMetric.PROPULSION_DURATION):
        comparison = _compare_phase_metrics(first, longer, metric, f"res49-duration-{metric.value}")
        assert comparison.state is ComparabilityState.COMPARABLE


def test_res49_trial_length_and_explicit_timestamp_origin_are_not_method_identity() -> None:
    first = _phase_fixture(
        "res49-trial-length-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    longer = _phase_fixture(
        "res49-trial-length-longer",
        (*_RES49_FIRST_TRACE, 0.0),
        takeoff_search_start_index=8,
    )
    assert (
        first[3][1].start_boundary.source_sample_count
        != longer[3][1].start_boundary.source_sample_count
    )
    assert (
        _compare_phase_metrics(
            first, longer, CMJPhaseMetric.BRAKING_DURATION, "res49-trial-length"
        ).state
        is ComparabilityState.COMPARABLE
    )

    explicit_first = _phase_fixture(
        "res49-time-origin-first",
        _RES49_FIRST_TRACE,
        timebase=ExplicitTimebase(tuple(10.0 + index / 1000.0 for index in range(10))),
        takeoff_search_start_index=8,
    )
    explicit_second = _phase_fixture(
        "res49-time-origin-second",
        _RES49_FIRST_TRACE,
        timebase=ExplicitTimebase(tuple(20.0 + index / 1000.0 for index in range(10))),
        takeoff_search_start_index=8,
    )
    assert explicit_first[3][1].start_time_s != explicit_second[3][1].start_time_s
    assert (
        _compare_phase_metrics(
            explicit_first,
            explicit_second,
            CMJPhaseMetric.BRAKING_DURATION,
            "res49-explicit-time-origin",
        ).state
        is ComparabilityState.COMPARABLE
    )


def test_res49_sampling_rate_and_timebase_kind_remain_material() -> None:
    regular_1000 = _phase_fixture(
        "res49-rate-1000",
        _RES49_FIRST_TRACE,
        timebase=RegularTimebase(1000.0),
        takeoff_search_start_index=8,
    )
    regular_500 = _phase_fixture(
        "res49-rate-500",
        _RES49_FIRST_TRACE,
        timebase=RegularTimebase(500.0),
        takeoff_search_start_index=8,
    )
    comparison = _compare_phase_metrics(
        regular_1000, regular_500, CMJPhaseMetric.BRAKING_DURATION, "res49-sampling-rate"
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH in comparison.reason_codes

    explicit = _phase_fixture(
        "res49-explicit-timebase",
        _RES49_FIRST_TRACE,
        timebase=ExplicitTimebase(tuple(index / 1000.0 for index in range(10))),
        takeoff_search_start_index=8,
    )
    comparison = _compare_phase_metrics(
        regular_1000, explicit, CMJPhaseMetric.BRAKING_DURATION, "res49-timebase-kind"
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH in comparison.reason_codes


@pytest.mark.parametrize(
    ("parameter_name", "parameter_value"),
    (
        ("onset_sigma_multiplier", 2.0),
        ("onset_dwell_samples", 2),
        ("takeoff_threshold_n", 21.0),
        ("takeoff_dwell_samples", 2),
    ),
)
def test_res49_detector_parameters_remain_method_identity(
    parameter_name: str, parameter_value: float | int
) -> None:
    first = _phase_fixture("res49-detector-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8)
    if parameter_name == "onset_sigma_multiplier":
        second = _phase_fixture(
            "res49-detector-second",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            onset_sigma_multiplier=float(parameter_value),
        )
    elif parameter_name == "onset_dwell_samples":
        second = _phase_fixture(
            "res49-detector-second",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            onset_dwell_samples=int(parameter_value),
        )
    elif parameter_name == "takeoff_threshold_n":
        second = _phase_fixture(
            "res49-detector-second",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            takeoff_threshold_n=float(parameter_value),
        )
    else:
        second = _phase_fixture(
            "res49-detector-second",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            takeoff_dwell_samples=int(parameter_value),
        )
    comparison = _compare_phase_metrics(
        first,
        second,
        CMJPhaseMetric.BRAKING_DURATION,
        f"res49-{parameter_name}",
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in comparison.reason_codes


@pytest.mark.parametrize(
    ("boundary_field", "boundary_value"),
    (
        ("tie_policy", "latest source sample among tied minimum velocity values"),
        ("velocity_threshold_policy", "registered positive threshold > 0.01 m/s"),
        ("interpolation_policy", "linear sub-sample interpolation"),
    ),
)
def test_res49_boundary_policy_differences_remain_material(
    boundary_field: str, boundary_value: str
) -> None:
    left_fixture = _phase_fixture(
        "res49-boundary-policy-left", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    right_fixture = _phase_fixture(
        "res49-boundary-policy-right", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    original = _phase_metric(left_fixture, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE)
    right_metric = _phase_metric(right_fixture, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE)
    if boundary_field == "tie_policy":
        changed_boundary = replace(
            right_metric.phase_occurrence.end_boundary,
            tie_policy=boundary_value,
        )
    elif boundary_field == "velocity_threshold_policy":
        changed_boundary = replace(
            right_metric.phase_occurrence.end_boundary,
            velocity_threshold_policy=boundary_value,
        )
    else:
        changed_boundary = replace(
            right_metric.phase_occurrence.end_boundary,
            interpolation_policy=boundary_value,
        )
    changed_phase = replace(right_metric.phase_occurrence, end_boundary=changed_boundary)
    changed = replace(right_metric, phase_occurrence=changed_phase)
    comparison = compare_cmj_phase_metrics(
        original,
        changed,
        claim=f"res49-boundary-{boundary_field}",
        request_id=InstanceIdentifier("comparability-request", f"res49-{boundary_field}"),
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in comparison.reason_codes


def test_res49_zero_reference_realization_is_not_method_identity() -> None:
    first = _phase_fixture(
        "res49-zero-first",
        _RES49_FIRST_TRACE,
        takeoff_search_start_index=8,
        velocity_start_index=1,
    )
    second = _phase_fixture(
        "res49-zero-second",
        _RES49_FIRST_TRACE,
        takeoff_search_start_index=8,
        velocity_start_index=2,
    )
    assert (
        first[3][1].source_velocity_initial_condition.sample_index
        != second[3][1].source_velocity_initial_condition.sample_index
    )
    comparison = _compare_phase_metrics(
        first, second, CMJPhaseMetric.BRAKING_DURATION, "res49-zero-reference-index"
    )
    assert comparison.state is ComparabilityState.COMPARABLE


def test_res49_weighing_segment_coordinates_and_qc_values_are_not_method_identity() -> None:
    first = _phase_fixture(
        "res49-zero-segment-first",
        _RES49_FIRST_TRACE,
        takeoff_search_start_index=8,
    )
    second = _phase_fixture(
        "res49-zero-segment-second",
        _RES49_QC_TRACE,
        weighing_start_index=1,
        weighing_end_index=4,
        takeoff_search_start_index=8,
    )
    first_reference = first[3][1].source_velocity_initial_condition
    second_reference = second[3][1].source_velocity_initial_condition
    assert (
        first_reference.weighing_segment.start_index
        != second_reference.weighing_segment.start_index
    )
    assert first[4].detector_parameters.baseline_standard_deviation_n != (
        second[4].detector_parameters.baseline_standard_deviation_n
    )
    comparison = _compare_phase_metrics(
        first, second, CMJPhaseMetric.BRAKING_DURATION, "res49-zero-segment-and-qc"
    )
    assert comparison.state is ComparabilityState.COMPARABLE


def test_res49_zero_reference_method_and_authority_state_remain_material() -> None:
    first = _phase_fixture(
        "res49-zero-method-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    changed_selection = _phase_fixture(
        "res49-zero-method-second",
        _RES49_FIRST_TRACE,
        takeoff_search_start_index=8,
        weighing_selection_parameters=(MetadataEntry("selection_window", "alternate"),),
    )
    comparison = _compare_phase_metrics(
        first, changed_selection, CMJPhaseMetric.BRAKING_DURATION, "res49-zero-method"
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PHASE_METRIC_METHOD_MISMATCH in comparison.reason_codes


def test_res49_integration_coordinates_are_realization_but_algorithm_is_registered() -> None:
    first = _phase_fixture(
        "res49-integration-first", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    second = _phase_fixture(
        "res49-integration-second", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    changed_interval = replace(
        second[3][1].source_velocity_integration_interval,
        end_index=8,
    )
    changed_phase = replace(second[3][1], source_velocity_integration_interval=changed_interval)
    changed_metric = replace(
        _phase_metric(second, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE),
        phase_occurrence=changed_phase,
    )
    comparison = compare_cmj_phase_metrics(
        _phase_metric(first, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE),
        changed_metric,
        claim="res49-integration-interval-realization",
        request_id=InstanceIdentifier("comparability-request", "res49-integration-interval"),
    )
    assert comparison.state is ComparabilityState.COMPARABLE
    assert first[3][1].source_velocity_integration_method.stable_id.endswith(
        "cmj-sample-attached-trapezoidal-v1@1.0.0"
    )


def test_res49_different_integration_algorithm_cannot_enter_the_v1_phase_contract() -> None:
    fixture = _phase_fixture(
        "res49-integration-method", _RES49_FIRST_TRACE, takeoff_search_start_index=8
    )
    alternate = RegistryReference(
        ScientificIdentifier("dynamislm", "integration-method", "alternate", "1.0.0"),
        "alternate integration method",
    )
    with pytest.raises(ValueError, match="registered trapezoidal"):
        replace(
            fixture[3][1].source_velocity_integration_interval,
            integration_method=alternate,
        )


def test_res49_loading_contract_remains_material() -> None:
    unloaded = _phase_fixture("res49-unloaded", _RES49_FIRST_TRACE, takeoff_search_start_index=8)
    loaded = _phase_fixture(
        "res49-loaded",
        _RES49_FIRST_TRACE,
        external_loading="stable-attached-supported-load",
        takeoff_search_start_index=8,
    )
    comparison = _compare_phase_metrics(
        unloaded, loaded, CMJPhaseMetric.BRAKING_DURATION, "res49-loading-contract"
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PROTOCOL_MISMATCH in comparison.reason_codes


def test_res49_provenance_coordinates_and_historical_serialization_hashes_are_preserved() -> None:
    _, net_force, _, phases, _, _ = _phase_fixture("phase-serialization")
    phase = phases[1]
    metric = _metric(calculate_cmj_phase_net_vertical_impulse(phase, net_force))
    assert SERIALIZATION_VERSION == 3
    assert phase.start_boundary.sample_index == 6
    assert phase.end_boundary.sample_index == 8
    assert phase.start_boundary.source_event_id is None
    assert phase.end_boundary.source_event_id is None
    assert phase.provenance.processing_runs
    assert metric.observation.identity.processing.method_parameters
    phase_json = canonical_json(phase)
    metric_json = canonical_json(metric)
    assert '"sample_index":6' in phase_json
    assert '"sample_index":8' in phase_json
    assert '"start_index":6' in metric_json
    assert '"end_index":8' in metric_json
    assert canonical_hash(phase) == (
        "sha256:65f8a45fb54060da0b2d2b59156b2f62837c9c6f82cfb8bb9968b7d75a5c0f01"
    )
    assert canonical_hash(metric) == (
        "sha256:040b3e6013d773d65d5c9f967fafaf3d7ab434ae48968c38044ee9dc6a66a11b"
    )
    restored_phase = from_canonical_json(phase_json, CMJPhaseOccurrence)
    restored_metric = from_canonical_json(metric_json, CMJPhaseMetricResult)
    assert canonical_json(restored_phase) == canonical_json(phase)
    assert canonical_json(restored_metric) == canonical_json(metric)


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
