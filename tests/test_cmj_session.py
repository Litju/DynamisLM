from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import overload

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    InstanceIdentifier,
    MetadataEntry,
    ScalarValue,
    ScientificMeasurementObservation,
    VectorValue,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import ComparabilityReasonCode, ComparabilityState
from dynamislm.measurement.cmj import (
    CMJ_ARITHMETIC_MEAN_V1,
    CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1,
    CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1,
    CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
    CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1,
    CMJ_SESSION_AGGREGATION_OPERATION,
    CMJ_TEST_FAMILY,
    CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    CMJJumpHeightResult,
    CMJPhaseMetric,
    CMJPhaseMetricResult,
    CMJTrialMetricValue,
    DeclaredCandidateTrialSet,
    ExplicitTimebase,
    RegularTimebase,
    SessionAggregationResult,
    SignalTimebase,
    TrialEligibilityDecision,
    TrialSelectionDecision,
    TrialSelectionDirection,
    aggregate_cmj_session,
    compare_cmj_session_summaries,
    evaluate_trial_eligibility,
    project_selected_trial,
    select_trials,
)
from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier
from dynamislm.measurement.result import ResultStatus, UncertaintyStatus
from dynamislm.refusal import RefusalReasonCode, RefusalResult
from test_cmj import _observation as _raw_observation
from test_cmj_jump_height import _flight_fixture, _velocity_fixture
from test_cmj_phases import (
    _RES49_FIRST_TRACE,
    _RES49_SECOND_TRACE,
    _UNIQUE_TRACE,
    _phase_fixture,
    _phase_metric,
)

ATHLETE = InstanceIdentifier("athlete", "res40-athlete")
SESSION = InstanceIdentifier("session", "res40-session")
TEST_INSTANCE = InstanceIdentifier("test-instance", "res40-test")


def _observation(value: CMJTrialMetricValue) -> ScientificMeasurementObservation:
    return value if isinstance(value, ScientificMeasurementObservation) else value.observation


@overload
def _bind(
    value: ScientificMeasurementObservation,
    trial: str,
    *,
    athlete: InstanceIdentifier = ATHLETE,
    session: InstanceIdentifier = SESSION,
    test_instance: InstanceIdentifier = TEST_INSTANCE,
) -> ScientificMeasurementObservation: ...


@overload
def _bind(
    value: CMJPhaseMetricResult,
    trial: str,
    *,
    athlete: InstanceIdentifier = ATHLETE,
    session: InstanceIdentifier = SESSION,
    test_instance: InstanceIdentifier = TEST_INSTANCE,
) -> CMJPhaseMetricResult: ...


@overload
def _bind(
    value: CMJJumpHeightResult,
    trial: str,
    *,
    athlete: InstanceIdentifier = ATHLETE,
    session: InstanceIdentifier = SESSION,
    test_instance: InstanceIdentifier = TEST_INSTANCE,
) -> CMJJumpHeightResult: ...


def _bind(
    value: CMJTrialMetricValue,
    trial: str,
    *,
    athlete: InstanceIdentifier = ATHLETE,
    session: InstanceIdentifier = SESSION,
    test_instance: InstanceIdentifier = TEST_INSTANCE,
) -> CMJTrialMetricValue:
    observation = _observation(value)
    context = replace(
        observation.context,
        athlete_id=athlete,
        session_id=session,
        test_instance_id=test_instance,
        trial_id=InstanceIdentifier("trial", trial),
    )
    bound_observation = replace(observation, context=context)
    if isinstance(value, ScientificMeasurementObservation):
        return bound_observation
    return replace(value, observation=bound_observation)


def _phase(
    suffix: str,
    trace: tuple[float, ...] = _UNIQUE_TRACE,
    metric: CMJPhaseMetric = CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE,
    timebase: SignalTimebase | None = None,
    onset_search_start_index: int = 4,
    takeoff_search_start_index: int = 9,
    onset_sigma_multiplier: float | None = None,
    onset_dwell_samples: int = 1,
    takeoff_threshold_n: float = 20.0,
    takeoff_dwell_samples: int = 1,
    velocity_start_index: int = 2,
    velocity_end_index: int = 9,
    zero_reference_sample_index: int | None = None,
    external_loading: str = "none",
) -> CMJPhaseMetricResult:
    fixture = _phase_fixture(
        suffix,
        trace,
        timebase=timebase,
        onset_search_start_index=onset_search_start_index,
        takeoff_search_start_index=takeoff_search_start_index,
        onset_sigma_multiplier=onset_sigma_multiplier,
        onset_dwell_samples=onset_dwell_samples,
        takeoff_threshold_n=takeoff_threshold_n,
        takeoff_dwell_samples=takeoff_dwell_samples,
        velocity_start_index=velocity_start_index,
        velocity_end_index=velocity_end_index,
        zero_reference_sample_index=zero_reference_sample_index,
        external_loading=external_loading,
    )
    return _phase_metric(fixture, metric)


def _candidate_set(values: tuple[CMJTrialMetricValue, ...]) -> DeclaredCandidateTrialSet:
    trial_ids: list[InstanceIdentifier] = []
    for value in values:
        trial_id = _observation(value).context.trial_id
        assert trial_id is not None
        trial_ids.append(trial_id)
    return DeclaredCandidateTrialSet(
        athlete_id=ATHLETE,
        session_id=SESSION,
        test_family=CMJ_TEST_FAMILY,
        trial_ids=tuple(trial_ids),
        candidate_observation_ids=tuple(_observation(value).observation_id for value in values),
    )


def _select_all(values: tuple[CMJTrialMetricValue, ...]) -> TrialSelectionDecision:
    candidate_set = _candidate_set(values)
    eligibility = evaluate_trial_eligibility(candidate_set, values)
    assert not isinstance(eligibility, RefusalResult)
    selection = select_trials(candidate_set, eligibility)
    assert isinstance(selection, TrialSelectionDecision)
    return selection


def _mean(
    values: tuple[CMJTrialMetricValue, ...],
    *,
    output_id: str,
) -> SessionAggregationResult:
    result = aggregate_cmj_session(
        _select_all(values),
        values,
        output_observation_id=InstanceIdentifier("observation", output_id),
    )
    assert isinstance(result, SessionAggregationResult)
    return result


def _assert_refusal(
    result: object,
    reason: RefusalReasonCode,
) -> RefusalResult:
    assert isinstance(result, RefusalResult)
    assert reason in result.reason_codes
    return result


def _raw_scalar(suffix: str, value: float) -> ScientificMeasurementObservation:
    raw = _raw_observation(suffix)
    return replace(raw, result=replace(raw.result, value=ScalarValue(value)))


def _numeric(value: CMJTrialMetricValue) -> float:
    scalar = _observation(value).result.value
    assert isinstance(scalar, ScalarValue)
    assert isinstance(scalar.value, int | float) and not isinstance(scalar.value, bool)
    return float(scalar.value)


def _extreme_selection(
    ranking_values: tuple[CMJTrialMetricValue, ...],
    *,
    direction: TrialSelectionDirection = TrialSelectionDirection.MAXIMIZE,
) -> TrialSelectionDecision:
    candidate_set = _candidate_set(ranking_values)
    eligibility = evaluate_trial_eligibility(candidate_set, ranking_values)
    assert not isinstance(eligibility, RefusalResult)
    first = ranking_values[0]
    metric = _observation(first).identity.semantic.metric_definition
    method: RegistryReference | None
    if isinstance(first, CMJJumpHeightResult):
        method = first.estimator
    else:
        method = _observation(first).identity.processing.registered_operation
    assert method is not None
    selection = select_trials(
        candidate_set,
        eligibility,
        selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
        ranking_observations=ranking_values,
        ranking_metric=metric,
        ranking_method=method,
        ranking_direction=direction,
        tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    )
    assert isinstance(selection, TrialSelectionDecision)
    return selection


def test_candidate_order_and_all_eligibility_are_explicit() -> None:
    first = _bind(_phase("candidate-a"), "a")
    second = _bind(_phase("candidate-b"), "b")
    candidate_set = _candidate_set((first, second))

    decisions = evaluate_trial_eligibility(candidate_set, (first, second))
    assert not isinstance(decisions, RefusalResult)
    assert tuple(decision.trial_id for decision in decisions) == candidate_set.trial_ids
    assert all(decision.status.value == "ELIGIBLE" for decision in decisions)

    selection = select_trials(candidate_set, decisions)
    assert isinstance(selection, TrialSelectionDecision)
    assert selection.selected_trial_ids == candidate_set.trial_ids
    assert selection.declared_candidate_count == 2
    assert selection.eligible_count == 2
    assert selection.selected_count == 2


def test_wrong_source_and_duplicate_candidate_trials_refuse_or_fail_closed() -> None:
    first = _bind(_phase("source-a"), "a")
    second = _bind(_phase("source-b"), "b", athlete=InstanceIdentifier("athlete", "other"))
    candidate_set = _candidate_set((first, _bind(_phase("source-c"), "b")))
    eligibility = evaluate_trial_eligibility(candidate_set, (first, second))
    _assert_refusal(eligibility, RefusalReasonCode.SESSION_SOURCE_MISMATCH)

    with pytest.raises(ValueError, match="distinct"):
        DeclaredCandidateTrialSet(
            ATHLETE,
            SESSION,
            CMJ_TEST_FAMILY,
            (InstanceIdentifier("trial", "a"), InstanceIdentifier("trial", "a")),
            (
                InstanceIdentifier("observation", "a"),
                InstanceIdentifier("observation", "b"),
            ),
        )


def test_unresolved_candidate_is_not_available_case_aggregation() -> None:
    first = _bind(_phase("missing-a"), "a")
    second = _bind(_phase("missing-b"), "b")
    candidate_set = _candidate_set((first, second))
    eligibility = evaluate_trial_eligibility(candidate_set, (first,))
    assert not isinstance(eligibility, RefusalResult)
    assert eligibility[1].status.value == "UNRESOLVED"

    selection = select_trials(candidate_set, eligibility)
    _assert_refusal(selection, RefusalReasonCode.TRIAL_SET_INCOMPLETE)


def test_registered_exclusion_recomputes_counts_honestly() -> None:
    first = _bind(_phase("excluded-a"), "a")
    second = _bind(_phase("excluded-b"), "b")
    candidate_set = _candidate_set((first, second))
    second_trial_id = second.observation.context.trial_id
    assert second_trial_id is not None
    excluded = TrialEligibilityDecision.excluded(
        second_trial_id,
        (_observation(second).observation_id,),
        policy=CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1,
        reason="registered QC exclusion for this trial",
    )
    eligibility = evaluate_trial_eligibility(candidate_set, (first,), exclusions=(excluded,))
    assert not isinstance(eligibility, RefusalResult)
    selection = select_trials(candidate_set, eligibility)
    assert isinstance(selection, TrialSelectionDecision)
    result = aggregate_cmj_session(selection, (first,))
    assert isinstance(result, SessionAggregationResult)
    assert result.declared_candidate_count == 2
    assert result.eligible_count == 1
    assert result.selected_count == 1
    assert result.contributing_count == 1
    assert result.selection_decision.excluded_trial_ids == (excluded.trial_id,)


def test_unregistered_exclusion_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="registered V1 policy"):
        TrialEligibilityDecision.excluded(
            InstanceIdentifier("trial", "excluded"),
            (InstanceIdentifier("observation", "excluded"),),
            policy=RegistryReference(
                ScientificIdentifier("synthetic", "eligibility-policy", "other", "1.0.0"),
                "Other exclusion policy",
            ),
            reason="not a RES-40 policy",
        )


def test_extreme_selection_requires_explicit_direction_and_comparable_ranking() -> None:
    first = _bind(_phase("extreme-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("extreme-b", _RES49_SECOND_TRACE), "b")
    candidate_set = _candidate_set((first, second))
    eligibility = evaluate_trial_eligibility(candidate_set, (first, second))
    assert not isinstance(eligibility, RefusalResult)
    metric = first.observation.identity.semantic.metric_definition
    method = first.observation.identity.processing.registered_operation
    assert method is not None

    missing_direction = select_trials(
        candidate_set,
        eligibility,
        selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
        ranking_observations=(first, second),
        ranking_metric=metric,
        ranking_method=method,
        tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    )
    _assert_refusal(missing_direction, RefusalReasonCode.RANKING_DIRECTION_REQUIRED)

    incompatible = _bind(
        _phase("extreme-c", _UNIQUE_TRACE, CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE), "b"
    )
    incompatible_set = _candidate_set((first, incompatible))
    incompatible_eligibility = evaluate_trial_eligibility(incompatible_set, (first, incompatible))
    assert not isinstance(incompatible_eligibility, RefusalResult)
    incompatible_result = select_trials(
        incompatible_set,
        incompatible_eligibility,
        selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
        ranking_observations=(first, incompatible),
        ranking_metric=metric,
        ranking_method=method,
        ranking_direction=TrialSelectionDirection.MAXIMIZE,
        tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    )
    _assert_refusal(incompatible_result, RefusalReasonCode.RANKING_METRICS_NOT_COMPARABLE)


def test_exact_extreme_ties_use_declared_order_not_incidental_ids() -> None:
    first = _bind(_phase("tie-first", _UNIQUE_TRACE), "first")
    second = _bind(_phase("tie-second", _UNIQUE_TRACE), "second")
    selection = _extreme_selection((first, second))
    assert selection.selected_trial_ids == (InstanceIdentifier("trial", "first"),)
    assert selection.ranking_observation_ids == (
        first.observation.observation_id,
        second.observation.observation_id,
    )


def test_selection_metric_and_reported_metric_remain_separate() -> None:
    ranking_a = _bind(_phase("rank-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("rank-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((ranking_a, ranking_b))
    assert selection.selected_trial_ids == (InstanceIdentifier("trial", "a"),)

    target_a = _bind(
        _phase("target-a", _RES49_FIRST_TRACE, CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE),
        "a",
    )
    target_b = _bind(
        _phase("target-b", _RES49_SECOND_TRACE, CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE),
        "b",
    )
    result = project_selected_trial(
        selection,
        (target_a, target_b),
        output_observation_id=InstanceIdentifier("observation", "selected-target"),
    )
    assert isinstance(result, SessionAggregationResult)
    assert result.aggregation_rule == CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1
    assert result.selected_trial_id == InstanceIdentifier("trial", "a")
    assert result.value == pytest.approx(_numeric(target_a))
    assert result.value != pytest.approx(_numeric(target_b))
    assert (
        result.selection_decision.ranking_metric
        == ranking_a.observation.identity.semantic.metric_definition
    )
    assert result.target_metric == target_a.observation.identity.semantic.metric_definition


def test_selected_projection_requires_only_the_selected_target() -> None:
    ranking_a = _bind(_phase("projection-ranking-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("projection-ranking-b", _UNIQUE_TRACE), "b")
    ranking_c = _bind(_phase("projection-ranking-c", _RES49_SECOND_TRACE), "c")
    selection = _extreme_selection((ranking_a, ranking_b, ranking_c))
    assert selection.selected_trial_ids == (InstanceIdentifier("trial", "b"),)

    target_b = _bind(
        _phase(
            "projection-target-b",
            _RES49_SECOND_TRACE,
            CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
        ),
        "b",
    )
    result = project_selected_trial(
        selection,
        (target_b,),
        output_observation_id=InstanceIdentifier("observation", "projection-selected-only"),
    )
    assert isinstance(result, SessionAggregationResult)
    assert result.selected_trial_id == InstanceIdentifier("trial", "b")
    assert result.contributing_trial_ids == (InstanceIdentifier("trial", "b"),)
    assert result.contributing_count == 1
    assert result.value == pytest.approx(_numeric(target_b))


def test_jump_height_selection_projects_a_different_target_from_the_same_trial() -> None:
    jump_a, _, _, _ = _flight_fixture("jump-selection-a")
    jump_b, _, _, _ = _flight_fixture("jump-selection-b", gravity_suffix="jump-selection-a")
    jump_a = _bind(jump_a, "a")
    jump_b = _bind(jump_b, "b")
    selection = _extreme_selection((jump_a, jump_b))
    assert selection.ranking_metric == jump_a.observation.identity.semantic.metric_definition
    assert selection.ranking_method == jump_a.estimator
    assert selection.ranking_values == (_numeric(jump_a), _numeric(jump_b))
    restored_selection = from_canonical_json(canonical_json(selection), TrialSelectionDecision)
    assert restored_selection == selection

    target_a = _bind(
        _phase("jump-target-a", _RES49_FIRST_TRACE, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE),
        "a",
    )
    target_b = _bind(
        _phase("jump-target-b", _RES49_SECOND_TRACE, CMJPhaseMetric.BRAKING_NET_VERTICAL_IMPULSE),
        "b",
    )
    result = project_selected_trial(
        selection,
        (target_a, target_b),
        output_observation_id=InstanceIdentifier("observation", "jump-selected-target"),
    )
    assert isinstance(result, SessionAggregationResult)
    assert result.selected_trial_id == InstanceIdentifier("trial", "a")
    assert result.value == pytest.approx(_numeric(target_a))
    assert result.value != pytest.approx(_numeric(target_b))
    assert result.target_metric == target_a.observation.identity.semantic.metric_definition


def test_arithmetic_mean_is_exact_scalar_mean_and_preserves_provenance() -> None:
    first = _bind(_phase("mean-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("mean-b", _RES49_SECOND_TRACE), "b")
    result = _mean((first, second), output_id="mean-result")
    assert result.value == pytest.approx((first.value + second.value) / 2.0)
    assert result.observation.context.trial_id is None
    assert (
        result.observation.identity.processing.registered_operation
        == CMJ_SESSION_AGGREGATION_OPERATION
    )
    assert (
        result.observation.identity.processing.trial_selection
        == CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1
    )
    assert result.observation.identity.processing.aggregation == CMJ_ARITHMETIC_MEAN_V1
    assert result.source_observation_ids == (
        first.observation.observation_id,
        second.observation.observation_id,
    )
    assert result.source_measurement_identity_ids
    assert result.observation.result.uncertainty.status is UncertaintyStatus.NOT_ASSESSED
    assert any(
        run.output_entity_id == result.observation.observation_id
        for run in result.observation.provenance.processing_runs
    )
    assert {
        evidence.reference.stable_id
        for evidence in result.observation.provenance.evidence_references
    } >= {
        "dynamislm:decision-record:res40-trial-selection@1.0.0",
        "dynamislm:decision-record:res40-session-aggregation@1.0.0",
    }
    with pytest.raises(FrozenInstanceError):
        result.observation.context.trial_id = InstanceIdentifier("trial", "mutate")  # type: ignore[misc]
    assert first.observation.context.trial_id == InstanceIdentifier("trial", "a")


def test_scalar_only_boundary_refuses_vectors_and_no_array_mean_is_attempted() -> None:
    first = _bind(_raw_scalar("scalar-a", 1.0), "a")
    vector_source = _raw_scalar("vector-b", 3.0)
    vector = _bind(
        replace(
            vector_source,
            result=replace(vector_source.result, value=VectorValue((3.0, 4.0))),
        ),
        "b",
    )
    result = aggregate_cmj_session(_select_all((first, vector)), (first, vector))
    _assert_refusal(result, RefusalReasonCode.AGGREGATION_REQUIRES_SCALAR)


def test_missing_target_metric_refuses_available_case_mean() -> None:
    first = _bind(_phase("target-missing-a"), "a")
    second = _bind(_phase("target-missing-b"), "b")
    selection = _select_all((first, second))
    result = aggregate_cmj_session(selection, (first,))
    refused = _assert_refusal(result, RefusalReasonCode.TRIAL_SET_INCOMPLETE)
    assert RefusalReasonCode.TARGET_METRIC_REQUIRED in refused.reason_codes


def test_refused_target_observation_does_not_enter_the_mean() -> None:
    first = _bind(_raw_scalar("target-status-a", 1.0), "a")
    second = _bind(_raw_scalar("target-status-b", 2.0), "b")
    selection = _select_all((first, second))
    invalid_target = replace(
        second,
        result=replace(second.result, status=ResultStatus.QUESTIONABLE),
    )
    result = aggregate_cmj_session(selection, (first, invalid_target))
    _assert_refusal(result, RefusalReasonCode.AGGREGATION_REQUIRES_SCALAR)


def test_mixed_jump_height_estimators_refuse_ranking_and_mean() -> None:
    flight, _, _, _ = _flight_fixture("session-flight")
    velocity, _, _, _ = _velocity_fixture("session-velocity")
    flight = _bind(flight, "a")
    velocity = _bind(velocity, "b")
    candidate_set = _candidate_set((flight, velocity))
    eligibility = evaluate_trial_eligibility(candidate_set, (flight, velocity))
    assert not isinstance(eligibility, RefusalResult)
    ranking = select_trials(
        candidate_set,
        eligibility,
        selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
        ranking_observations=(flight, velocity),
        ranking_metric=flight.observation.identity.semantic.metric_definition,
        ranking_method=flight.estimator,
        ranking_direction=TrialSelectionDirection.MAXIMIZE,
        tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    )
    _assert_refusal(ranking, RefusalReasonCode.RANKING_METRICS_NOT_COMPARABLE)

    selection = select_trials(candidate_set, eligibility)
    assert isinstance(selection, TrialSelectionDecision)
    result = aggregate_cmj_session(selection, (flight, velocity))
    refused = _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)
    assert RefusalReasonCode.ESTIMATOR_MISMATCH in refused.reason_codes


def test_configured_phase_detector_search_start_is_method_identity() -> None:
    baseline = _bind(_phase("search-baseline", _RES49_FIRST_TRACE), "a")
    onset_changed = _bind(
        _phase("search-onset", _RES49_FIRST_TRACE, onset_search_start_index=5), "b"
    )
    selection = _select_all((baseline, onset_changed))
    result = aggregate_cmj_session(selection, (baseline, onset_changed))
    refused = _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)
    assert RefusalReasonCode.PHASE_COMPARABILITY_UNESTABLISHED not in refused.reason_codes
    assert RefusalReasonCode.PHASE_METHOD_MISMATCH in refused.reason_codes

    takeoff_changed = _bind(
        _phase("search-takeoff", _RES49_FIRST_TRACE, takeoff_search_start_index=8), "b"
    )
    result = aggregate_cmj_session(
        _select_all((baseline, takeoff_changed)), (baseline, takeoff_changed)
    )
    refused = _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)
    assert RefusalReasonCode.PHASE_METHOD_MISMATCH in refused.reason_codes


def test_other_configured_detector_parameters_remain_method_identity() -> None:
    baseline = _bind(
        _phase("detector-baseline", _RES49_FIRST_TRACE, takeoff_search_start_index=8), "a"
    )
    changed_values = (
        _phase(
            "detector-sigma",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            onset_sigma_multiplier=2.0,
        ),
        _phase(
            "detector-onset-dwell",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            onset_dwell_samples=2,
        ),
        _phase(
            "detector-threshold",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            takeoff_threshold_n=21.0,
        ),
        _phase(
            "detector-takeoff-dwell",
            _RES49_FIRST_TRACE,
            takeoff_search_start_index=8,
            takeoff_dwell_samples=2,
        ),
    )
    for index, changed_value in enumerate(changed_values):
        changed = _bind(changed_value, f"b-{index}")
        result = aggregate_cmj_session(_select_all((baseline, changed)), (baseline, changed))
        refused = _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)
        assert RefusalReasonCode.PHASE_METHOD_MISMATCH in refused.reason_codes


def test_observed_event_coordinates_and_trial_support_remain_instance_data() -> None:
    first = _bind(_phase("coordinates-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("coordinates-b", _RES49_SECOND_TRACE), "b")
    result = _mean((first, second), output_id="coordinates-result")
    assert result.value == pytest.approx((first.value + second.value) / 2.0)
    assert (
        first.phase_occurrence.start_boundary.sample_index
        != second.phase_occurrence.start_boundary.sample_index
    )

    long_trace = _bind(_phase("long-support", (*_UNIQUE_TRACE, 0.0)), "c")
    short_trace = _bind(_phase("short-support", _UNIQUE_TRACE), "d")
    result = _mean((long_trace, short_trace), output_id="support-result")
    assert result.contributing_count == 2


def test_realized_velocity_endpoints_and_zero_reference_do_not_become_method_identity() -> None:
    baseline = _bind(_phase("realization-baseline"), "a")
    changed_interval = _bind(
        _phase("realization-interval", velocity_start_index=1, velocity_end_index=9), "b"
    )
    result = aggregate_cmj_session(
        _select_all((baseline, changed_interval)), (baseline, changed_interval)
    )
    assert isinstance(result, SessionAggregationResult)

    changed_zero = _bind(
        _phase("realization-zero", velocity_start_index=1, zero_reference_sample_index=1), "b"
    )
    result = aggregate_cmj_session(_select_all((baseline, changed_zero)), (baseline, changed_zero))
    assert isinstance(result, SessionAggregationResult)


def test_explicit_timestamp_origin_is_instance_but_sampling_kind_is_method_identity() -> None:
    explicit_first = _bind(
        _phase(
            "session-explicit-origin-first",
            _RES49_FIRST_TRACE,
            timebase=ExplicitTimebase(tuple(10.0 + index / 1000.0 for index in range(10))),
            takeoff_search_start_index=8,
        ),
        "a",
    )
    explicit_second = _bind(
        _phase(
            "session-explicit-origin-second",
            _RES49_FIRST_TRACE,
            timebase=ExplicitTimebase(tuple(20.0 + index / 1000.0 for index in range(10))),
            takeoff_search_start_index=8,
        ),
        "b",
    )
    comparable = aggregate_cmj_session(
        _select_all((explicit_first, explicit_second)), (explicit_first, explicit_second)
    )
    assert isinstance(comparable, SessionAggregationResult)

    regular_500 = _bind(
        _phase(
            "session-regular-500",
            _RES49_FIRST_TRACE,
            timebase=RegularTimebase(500.0),
            takeoff_search_start_index=8,
        ),
        "b",
    )
    refused = aggregate_cmj_session(
        _select_all((explicit_first, regular_500)), (explicit_first, regular_500)
    )
    _assert_refusal(refused, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)


def test_acquisition_and_loading_mismatches_are_not_harmonized() -> None:
    first = _bind(_raw_scalar("device-a", 1.0), "a")
    second_source = _raw_scalar("device-b", 2.0)
    changed_identity = replace(
        second_source.identity,
        acquisition=replace(
            second_source.identity.acquisition,
            device=RegistryReference(
                ScientificIdentifier("synthetic", "device", "other-platform", "1.0.0"),
                "Other platform",
            ),
        ),
    )
    second = _bind(replace(second_source, identity=changed_identity), "b")
    result = aggregate_cmj_session(_select_all((first, second)), (first, second))
    refused = _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)
    assert RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED in refused.reason_codes

    loaded = _bind(_phase("loaded", external_loading="stable-attached-supported-load"), "b")
    phase = _bind(_phase("unloaded"), "a")
    result = aggregate_cmj_session(_select_all((phase, loaded)), (phase, loaded))
    _assert_refusal(result, RefusalReasonCode.TARGET_METRICS_NOT_COMPARABLE)


def test_session_summary_comparability_retains_rule_and_count_identity() -> None:
    left_a = _bind(_phase("summary-left-a", _RES49_FIRST_TRACE), "a")
    left_b = _bind(_phase("summary-left-b", _RES49_SECOND_TRACE), "b")
    right_a = _bind(_phase("summary-right-a", _RES49_FIRST_TRACE), "c")
    right_b = _bind(_phase("summary-right-b", _RES49_SECOND_TRACE), "d")
    left = _mean((left_a, left_b), output_id="summary-left")
    right = _mean((right_a, right_b), output_id="summary-right")
    comparable = compare_cmj_session_summaries(left, right, claim="compare CMJ session means")
    assert comparable.state is ComparabilityState.COMPARABLE

    third = _bind(_phase("summary-right-c", _UNIQUE_TRACE), "e")
    right_three = _mean((right_a, right_b, third), output_id="summary-right-three")
    count_difference = compare_cmj_session_summaries(
        left, right_three, claim="compare mean-of-two and mean-of-three"
    )
    assert count_difference.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert (
        ComparabilityReasonCode.SESSION_CANDIDATE_COUNT_MISMATCH.value
        in count_difference.reason_codes
    )
    assert (
        ComparabilityReasonCode.SESSION_CONTRIBUTING_COUNT_MISMATCH.value
        in count_difference.reason_codes
    )


def test_maximum_and_mean_are_not_directly_comparable_even_with_same_count() -> None:
    first = _bind(_phase("max-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("max-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    maximum = project_selected_trial(
        selection,
        (first, second),
        output_observation_id=InstanceIdentifier("observation", "maximum-result"),
    )
    assert isinstance(maximum, SessionAggregationResult)
    mean = _mean((first, second), output_id="mean-for-comparison")
    comparison = compare_cmj_session_summaries(
        maximum, mean, claim="compare selected maximum with arithmetic mean"
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert (
        ComparabilityReasonCode.SESSION_AGGREGATION_RULE_MISMATCH.value in comparison.reason_codes
    )


def test_maximum_opportunity_count_is_material() -> None:
    first = _bind(_phase("max-count-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("max-count-b", _RES49_SECOND_TRACE), "b")
    third = _bind(_phase("max-count-c", _UNIQUE_TRACE), "c")
    maximum_two = project_selected_trial(
        _extreme_selection((first, second)),
        (first, second),
        output_observation_id=InstanceIdentifier("observation", "maximum-two-result"),
    )
    maximum_three = project_selected_trial(
        _extreme_selection((first, second, third)),
        (first, second, third),
        output_observation_id=InstanceIdentifier("observation", "maximum-three-result"),
    )
    assert isinstance(maximum_two, SessionAggregationResult)
    assert isinstance(maximum_three, SessionAggregationResult)
    comparison = compare_cmj_session_summaries(
        maximum_two,
        maximum_three,
        claim="compare maximum-of-two with maximum-of-three",
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SESSION_CANDIDATE_COUNT_MISMATCH.value in comparison.reason_codes
    assert ComparabilityReasonCode.SESSION_ELIGIBLE_COUNT_MISMATCH.value in comparison.reason_codes


def test_session_result_roundtrip_hash_and_serialization_version_are_stable() -> None:
    first = _bind(_phase("roundtrip-a"), "a")
    second = _bind(_phase("roundtrip-b"), "b")
    result = _mean((first, second), output_id="roundtrip-result")
    serialized = canonical_json(result)
    restored = from_canonical_json(serialized, SessionAggregationResult)
    assert restored == result
    assert canonical_hash(restored) == canonical_hash(result)
    assert SERIALIZATION_VERSION == 3


def test_invalid_source_observation_status_is_unresolved_without_implicit_exclusion() -> None:
    valid = _bind(_raw_scalar("status-valid", 1.0), "a")
    invalid_source = _raw_scalar("status-invalid", 2.0)
    invalid = _bind(
        replace(
            invalid_source,
            result=replace(invalid_source.result, status=ResultStatus.INVALID),
        ),
        "b",
    )
    candidate_set = _candidate_set((valid, invalid))
    eligibility = evaluate_trial_eligibility(candidate_set, (valid, invalid))
    assert not isinstance(eligibility, RefusalResult)
    assert eligibility[1].status.value == "UNRESOLVED"
    _assert_refusal(
        select_trials(candidate_set, eligibility), RefusalReasonCode.TRIAL_SET_INCOMPLETE
    )


def test_phase_occurrence_cannot_drop_source_event_processing_lineage() -> None:
    phase = _phase_fixture("event-lineage-guard")[3][1]
    removed_runs = tuple(
        run
        for run in phase.provenance.processing_runs
        if run.method.identifier.object_type == "event-method"
        and run.output_entity_id.instance_type == "event-occurrence"
    )
    removed_run_ids = {run.processing_run_id.qualified for run in removed_runs}
    with pytest.raises(ValueError, match="movement-onset and takeoff event processing runs"):
        replace(
            phase,
            provenance=replace(
                phase.provenance,
                processing_runs=tuple(
                    run for run in phase.provenance.processing_runs if run not in removed_runs
                ),
                lineage_edges=tuple(
                    edge
                    for edge in phase.provenance.lineage_edges
                    if edge.from_id not in removed_run_ids and edge.to_id not in removed_run_ids
                ),
            ),
        )


def test_phase_occurrence_cannot_replace_source_detector_parameters_with_none() -> None:
    phase = _phase_fixture("event-parameter-guard")[3][1]
    damaged_runs = tuple(
        replace(
            run,
            parameters=tuple(
                MetadataEntry(entry.key, None) if entry.key == "detector_parameters" else entry
                for entry in run.parameters
            ),
        )
        if (
            run.method.identifier.object_type == "event-method"
            and run.output_entity_id.instance_type == "event-occurrence"
        )
        else run
        for run in phase.provenance.processing_runs
    )
    with pytest.raises(ValueError, match="detector parameters"):
        replace(phase, provenance=replace(phase.provenance, processing_runs=damaged_runs))
