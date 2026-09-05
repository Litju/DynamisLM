from __future__ import annotations

import json
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
from dynamislm.comparability import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityState,
)
from dynamislm.measurement.cmj import (
    CMJ_ARITHMETIC_MEAN_V1,
    CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1,
    CMJ_SELECT_ALL_DECLARED_ELIGIBLE_V1,
    CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
    CMJ_SELECTED_SINGLE_TRIAL_PROJECTION_V1,
    CMJ_SESSION_AGGREGATION_OPERATION,
    CMJ_TEST_FAMILY,
    CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    CMJIntegrationInterval,
    CMJJumpHeightResult,
    CMJMeasurementIdentity,
    CMJPhaseMetric,
    CMJPhaseMetricResult,
    CMJTrialMetricValue,
    DeclaredCandidateTrialSet,
    ExplicitTimebase,
    NetVerticalForceResult,
    NetVerticalImpulseResult,
    RegularTimebase,
    SessionAggregationResult,
    SignalTimebase,
    TrialEligibilityDecision,
    TrialSelectionDecision,
    TrialSelectionDirection,
    aggregate_cmj_session,
    compare_cmj_session_summaries,
    derive_net_vertical_force,
    evaluate_trial_eligibility,
    integrate_net_vertical_impulse,
    project_selected_trial,
    select_trials,
)
from dynamislm.measurement.identity import (
    MeasurementIdentity,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentity,
)
from dynamislm.measurement.result import ResultStatus, UncertaintyStatus
from dynamislm.provenance.models import LineageEdge, LineageRelation
from dynamislm.refusal import RefusalReasonCode, RefusalResult
from test_cmj import _mechanics_fixture
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


@overload
def _bind(
    value: NetVerticalImpulseResult,
    trial: str,
    *,
    athlete: InstanceIdentifier = ATHLETE,
    session: InstanceIdentifier = SESSION,
    test_instance: InstanceIdentifier = TEST_INSTANCE,
) -> NetVerticalImpulseResult: ...


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


def _unregistered_reference(object_type: str, key: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("synthetic", object_type, key, "1.0.0"),
        f"Unregistered {key}",
    )


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


def _legacy_selection(selection: TrialSelectionDecision) -> TrialSelectionDecision:
    envelope = json.loads(canonical_json(selection))
    for field_name in ("ranking_method_key", "ranking_provenance", "ranking_authority"):
        del envelope["payload"][field_name]
    restored = from_canonical_json(json.dumps(envelope), TrialSelectionDecision)
    assert isinstance(restored, TrialSelectionDecision)
    return restored


def _legacy_summary(summary: SessionAggregationResult) -> SessionAggregationResult:
    envelope = json.loads(canonical_json(summary))
    selection_payload = envelope["payload"]["selection_decision"]
    for field_name in ("ranking_method_key", "ranking_provenance", "ranking_authority"):
        del selection_payload[field_name]
    restored = from_canonical_json(json.dumps(envelope), SessionAggregationResult)
    assert isinstance(restored, SessionAggregationResult)
    return restored


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


def test_selected_projection_refuses_missing_or_mismatched_target_sources() -> None:
    ranking_a = _bind(_phase("target-source-ranking-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("target-source-ranking-b", _UNIQUE_TRACE), "b")
    selection = _extreme_selection((ranking_a, ranking_b))
    target_metric = CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE

    target_a = _bind(_phase("target-source-a", _RES49_FIRST_TRACE, target_metric), "a")
    _assert_refusal(
        project_selected_trial(selection, (target_a,)), RefusalReasonCode.TRIAL_SET_INCOMPLETE
    )

    wrong_athlete = _bind(
        _phase("target-source-athlete", _UNIQUE_TRACE, target_metric),
        "b",
        athlete=InstanceIdentifier("athlete", "other"),
    )
    _assert_refusal(
        project_selected_trial(selection, (wrong_athlete,)),
        RefusalReasonCode.SESSION_SOURCE_MISMATCH,
    )

    wrong_session = _bind(
        _phase("target-source-session", _UNIQUE_TRACE, target_metric),
        "b",
        session=InstanceIdentifier("session", "other"),
    )
    _assert_refusal(
        project_selected_trial(selection, (wrong_session,)),
        RefusalReasonCode.SESSION_SOURCE_MISMATCH,
    )

    wrong_trial = _bind(_phase("target-source-trial", _UNIQUE_TRACE, target_metric), "a")
    _assert_refusal(
        project_selected_trial(selection, (wrong_trial,)), RefusalReasonCode.TRIAL_SET_INCOMPLETE
    )

    source = _bind(_phase("target-source-family", _UNIQUE_TRACE, target_metric), "b")
    source_identity = source.observation.identity
    assert isinstance(source_identity, CMJMeasurementIdentity)
    wrong_family_identity = MeasurementIdentity(
        identity_id=source_identity.identity_id,
        semantic=SemanticIdentity(
            construct=source_identity.semantic.construct,
            test_family=_unregistered_reference("test-family", "other-family"),
            protocol=source_identity.semantic.protocol,
            measurand=source_identity.semantic.measurand,
            metric_definition=source_identity.semantic.metric_definition,
        ),
        acquisition=source_identity.acquisition,
        processing=source_identity.processing,
        version=source_identity.version,
    )
    wrong_family = replace(source.observation, identity=wrong_family_identity)
    _assert_refusal(
        project_selected_trial(selection, (wrong_family,)),
        RefusalReasonCode.SESSION_SOURCE_MISMATCH,
    )


def test_arithmetic_mean_requires_every_selected_target() -> None:
    first = _bind(_phase("mean-selected-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("mean-selected-b", _RES49_SECOND_TRACE), "b")
    third = _bind(_phase("mean-selected-c", _UNIQUE_TRACE), "c")
    selection = _select_all((first, second, third))
    refused = aggregate_cmj_session(selection, (first, second))
    _assert_refusal(refused, RefusalReasonCode.TRIAL_SET_INCOMPLETE)


def test_selection_decision_self_validates_registered_rules_and_winners() -> None:
    first = _bind(_phase("self-validating-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("self-validating-b", _RES49_SECOND_TRACE), "b")
    all_selection = _select_all((first, second))
    first_trial = InstanceIdentifier("trial", "a")
    second_trial = InstanceIdentifier("trial", "b")

    with pytest.raises(ValueError, match="every eligible"):
        replace(all_selection, selected_trial_ids=(first_trial,))
    with pytest.raises(ValueError, match="ranking metadata"):
        replace(
            all_selection,
            ranking_metric=first.observation.identity.semantic.metric_definition,
        )
    with pytest.raises(ValueError, match="registered CMJ V1"):
        replace(
            all_selection,
            selection_rule=_unregistered_reference("selection-rule", "not-registered"),
        )

    extreme = _extreme_selection((first, second))
    wrong_trial = second_trial if extreme.selected_trial_ids == (first_trial,) else first_trial
    with pytest.raises(ValueError, match="deterministic ranking winner"):
        replace(extreme, selected_trial_ids=(wrong_trial,))

    minimum = _extreme_selection(
        (first, second),
        direction=TrialSelectionDirection.MINIMIZE,
    )
    minimum_wrong_trial = (
        second_trial if minimum.selected_trial_ids == (first_trial,) else first_trial
    )
    with pytest.raises(ValueError, match="deterministic ranking winner"):
        replace(minimum, selected_trial_ids=(minimum_wrong_trial,))

    with pytest.raises(ValueError, match="ranking method identity"):
        replace(extreme, ranking_method_key=None)
    with pytest.raises(ValueError, match="canonical|selection key"):
        replace(extreme, ranking_method_key="forged-ranking-method-key")
    with pytest.raises(ValueError, match="canonical payload"):
        replace(extreme, ranking_method_key='{"serialization_version":3}')
    altered_values = (extreme.ranking_values[0] + 0.001, *extreme.ranking_values[1:])
    with pytest.raises(ValueError, match="selection value"):
        replace(extreme, ranking_values=altered_values)
    with pytest.raises(ValueError, match="selection method"):
        replace(
            extreme,
            ranking_method=_unregistered_reference("registered-operation", "forged-method"),
        )
    with pytest.raises(ValueError, match="ranking observation authority"):
        replace(extreme, ranking_authority=())
    with pytest.raises(ValueError, match="tie policy"):
        replace(
            extreme,
            tie_policy=_unregistered_reference("tie-policy", "not-registered"),
        )
    with pytest.raises(ValueError, match="ranking (observation IDs|provenance)"):
        replace(
            extreme,
            ranking_observation_ids=tuple(reversed(extreme.ranking_observation_ids)),
        )
    with pytest.raises(ValueError, match="every ranking value"):
        replace(extreme, ranking_values=extreme.ranking_values[:-1])
    with pytest.raises(ValueError, match="finite"):
        replace(extreme, ranking_values=(float("nan"), *extreme.ranking_values[1:]))
    with pytest.raises(ValueError, match="finite"):
        replace(extreme, ranking_values=(float("inf"), *extreme.ranking_values[1:]))

    tie_first = _bind(_phase("self-validating-tie-a", _UNIQUE_TRACE), "a")
    tie_second = _bind(_phase("self-validating-tie-b", _UNIQUE_TRACE), "b")
    tie_selection = _extreme_selection((tie_first, tie_second))
    with pytest.raises(ValueError, match="deterministic ranking winner"):
        replace(tie_selection, selected_trial_ids=(second_trial,))

    excluded = TrialEligibilityDecision.excluded(
        second_trial,
        (second.observation.observation_id,),
        policy=CMJ_EXPLICIT_TRIAL_EXCLUSION_POLICY_V1,
        reason="registered exclusion",
    )
    candidate_set = _candidate_set((first, second))
    eligibility = evaluate_trial_eligibility(candidate_set, (first,), exclusions=(excluded,))
    assert not isinstance(eligibility, RefusalResult)
    excluded_selection = select_trials(candidate_set, eligibility)
    assert isinstance(excluded_selection, TrialSelectionDecision)
    with pytest.raises(ValueError, match="eligible"):
        replace(excluded_selection, selected_trial_ids=(second_trial,))


def test_selection_rejects_forged_eligibility_observation_ids_on_wire_decode() -> None:
    first = _bind(_phase("forged-eligibility-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("forged-eligibility-b", _RES49_SECOND_TRACE), "b")
    selection = _select_all((first, second))
    envelope = json.loads(canonical_json(selection))
    envelope["payload"]["eligibility_decisions"][0]["observation_ids"] = [
        json.loads(canonical_json(InstanceIdentifier("observation", "forged")))["payload"]
    ]

    with pytest.raises(ValueError, match="invalid|candidate observation IDs"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_selection_rejects_semantically_empty_modern_ranking_key() -> None:
    first = _bind(_phase("forged-key-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("forged-key-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    envelope = json.loads(canonical_json(selection))
    forged_key = canonical_json({"forged": "ranking-authority"})
    envelope["payload"]["ranking_method_key"] = forged_key
    for authority in envelope["payload"]["ranking_authority"]:
        authority["ranking_method_key"] = forged_key

    with pytest.raises(ValueError, match="invalid|declared metric and method"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_selection_rejects_extra_modern_ranking_key_fields_on_wire_decode() -> None:
    first, _, _, _ = _flight_fixture("forged-key-shape-a", gravity_suffix="shared")
    second, _, _, _ = _flight_fixture("forged-key-shape-b", gravity_suffix="shared")
    selection = _extreme_selection((_bind(first, "a"), _bind(second, "b")))
    assert selection.ranking_method_key is not None
    key_envelope = json.loads(selection.ranking_method_key)
    assert isinstance(key_envelope["payload"], dict)
    key_envelope["payload"]["forged"] = "ranking-semantics"
    forged_key = json.dumps(key_envelope, separators=(",", ":"), sort_keys=True)

    envelope = json.loads(canonical_json(selection))
    envelope["payload"]["ranking_method_key"] = forged_key
    for authority in envelope["payload"]["ranking_authority"]:
        authority["ranking_method_key"] = forged_key

    with pytest.raises(ValueError, match="invalid|known ranking key shape"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_selection_rejects_nested_jump_method_semantics_on_wire_decode() -> None:
    first, _, _, _ = _flight_fixture("forged-nested-key-a", gravity_suffix="shared")
    second, _, _, _ = _flight_fixture("forged-nested-key-b", gravity_suffix="shared")
    selection = _extreme_selection((_bind(first, "a"), _bind(second, "b")))
    assert selection.ranking_method_key is not None
    key_envelope = json.loads(selection.ranking_method_key)
    assert isinstance(key_envelope["payload"], dict)
    key_envelope["payload"]["method"] = {
        "legitimate_method": key_envelope["payload"]["method"],
        "forged_semantics": {"ranking_window": "invented"},
    }
    forged_key = json.dumps(key_envelope, separators=(",", ":"), sort_keys=True)

    envelope = json.loads(canonical_json(selection))
    envelope["payload"]["ranking_method_key"] = forged_key
    for authority in envelope["payload"]["ranking_authority"]:
        authority["ranking_method_key"] = forged_key

    with pytest.raises(ValueError, match="invalid|registered jump method semantics"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_selection_rejects_changed_modern_ranking_key_provenance_semantics() -> None:
    first = _bind(_phase("forged-key-value-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("forged-key-value-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    assert selection.ranking_method_key is not None
    key_envelope = json.loads(selection.ranking_method_key)
    assert isinstance(key_envelope["payload"], list)
    detector_parameters = key_envelope["payload"][6][0][2]
    assert isinstance(detector_parameters, list)
    for parameter in detector_parameters:
        if parameter[0] == "search_start_index":
            parameter[1] = 5
            break
    else:
        pytest.fail("expected a search_start_index ranking parameter")
    forged_key = json.dumps(key_envelope, separators=(",", ":"), sort_keys=True)

    envelope = json.loads(canonical_json(selection))
    envelope["payload"]["ranking_method_key"] = forged_key
    for authority in envelope["payload"]["ranking_authority"]:
        authority["ranking_method_key"] = forged_key

    with pytest.raises(ValueError, match="invalid|ranking provenance semantics"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_selection_rejects_cross_trial_candidate_ranking_authority_repair() -> None:
    first = _bind(_phase("repaired-authority-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("repaired-authority-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    left, right = selection.ranking_authority
    swapped_left = replace(left, observation_id=right.observation_id, provenance=right.provenance)
    swapped_right = replace(right, observation_id=left.observation_id, provenance=left.provenance)

    with pytest.raises(ValueError, match="declared trial mapping"):
        replace(
            selection,
            ranking_observation_ids=(right.observation_id, left.observation_id),
            ranking_provenance=(right.provenance, left.provenance),
            ranking_authority=(swapped_left, swapped_right),
        )


def test_selection_rejects_forged_ranking_authority_source_binding() -> None:
    first = _bind(_phase("forged-ranking-source-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("forged-ranking-source-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    authority = selection.ranking_authority[0]
    forged_observation_id = InstanceIdentifier("observation", "forged-ranking-source")
    processing_run = authority.provenance.processing_runs[0]
    forged_provenance = replace(
        authority.provenance,
        lineage_edges=(
            *authority.provenance.lineage_edges,
            LineageEdge(
                forged_observation_id.qualified,
                processing_run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
        ),
    )

    with pytest.raises(ValueError, match="observation output"):
        replace(
            authority,
            observation_id=forged_observation_id,
            provenance=forged_provenance,
        )


def test_select_all_rejects_ranking_arguments_at_selection_boundary() -> None:
    first = _bind(_phase("select-all-ranking-a"), "a")
    second = _bind(_phase("select-all-ranking-b"), "b")
    candidate_set = _candidate_set((first, second))
    eligibility = evaluate_trial_eligibility(candidate_set, (first, second))
    assert not isinstance(eligibility, RefusalResult)
    result = select_trials(
        candidate_set,
        eligibility,
        ranking_metric=first.observation.identity.semantic.metric_definition,
    )
    _assert_refusal(result, RefusalReasonCode.SESSION_SOURCE_MISMATCH)


def test_ranking_method_key_excludes_trial_instance_coordinates() -> None:
    first = _bind(_phase("ranking-key-coordinate-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("ranking-key-coordinate-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    assert selection.ranking_method_key is not None
    assert first.observation.observation_id.qualified not in selection.ranking_method_key
    assert second.observation.observation_id.qualified not in selection.ranking_method_key
    assert "trial:a" not in selection.ranking_method_key
    assert "trial:b" not in selection.ranking_method_key

    explicit_first = _bind(
        _phase(
            "ranking-key-explicit-a",
            _RES49_FIRST_TRACE,
            timebase=ExplicitTimebase(tuple(10.0 + index / 1000.0 for index in range(10))),
        ),
        "a",
    )
    explicit_second = _bind(
        _phase(
            "ranking-key-explicit-b",
            _RES49_SECOND_TRACE,
            timebase=ExplicitTimebase(tuple(20.0 + index / 1000.0 for index in range(10))),
        ),
        "b",
    )
    explicit_selection = _extreme_selection((explicit_first, explicit_second))
    shifted_first = _bind(
        _phase(
            "ranking-key-explicit-shifted-a",
            _RES49_FIRST_TRACE,
            timebase=ExplicitTimebase(tuple(30.0 + index / 1000.0 for index in range(10))),
        ),
        "a",
    )
    shifted_second = _bind(
        _phase(
            "ranking-key-explicit-shifted-b",
            _RES49_SECOND_TRACE,
            timebase=ExplicitTimebase(tuple(40.0 + index / 1000.0 for index in range(10))),
        ),
        "b",
    )
    shifted_selection = _extreme_selection((shifted_first, shifted_second))
    assert explicit_selection.ranking_method_key == shifted_selection.ranking_method_key

    jump_a, _, _, _ = _flight_fixture("ranking-key-jump-a", gravity_suffix="shared")
    jump_b, _, _, _ = _flight_fixture("ranking-key-jump-b", gravity_suffix="shared")
    jump_a = _bind(jump_a, "a")
    jump_b = _bind(jump_b, "b")
    jump_selection = _extreme_selection((jump_a, jump_b))
    assert jump_selection.ranking_method_key is not None
    assert jump_a.observation.observation_id.qualified not in jump_selection.ranking_method_key
    assert jump_b.observation.observation_id.qualified not in jump_selection.ranking_method_key
    assert "trial:a" not in jump_selection.ranking_method_key
    assert "trial:b" not in jump_selection.ranking_method_key


def test_mechanics_ranking_method_key_excludes_source_instance_identity() -> None:
    first_fixture = _mechanics_fixture(
        "ranking-mechanics-a",
        (1.0, 1.0, 3.0, 3.0),
    )
    second_fixture = _mechanics_fixture(
        "ranking-mechanics-b",
        (1.0, 1.0, 3.0, 3.0),
    )
    first_net_force = derive_net_vertical_force(
        first_fixture[1], first_fixture[2], first_fixture[3]
    )
    second_net_force = derive_net_vertical_force(
        second_fixture[1], second_fixture[2], second_fixture[3]
    )
    assert isinstance(first_net_force, NetVerticalForceResult)
    assert isinstance(second_net_force, NetVerticalForceResult)
    first = integrate_net_vertical_impulse(
        first_net_force,
        CMJIntegrationInterval.explicit_sample(first_net_force.series.series_id, 0, 3),
    )
    second = integrate_net_vertical_impulse(
        second_net_force,
        CMJIntegrationInterval.explicit_sample(second_net_force.series.series_id, 0, 3),
    )
    assert not isinstance(first, RefusalResult)
    assert not isinstance(second, RefusalResult)
    first = _bind(first, "a")
    second = _bind(second, "b")

    selection = _extreme_selection((first, second))
    assert selection.ranking_method_key is not None
    assert selection.ranking_method_key == selection.ranking_authority[0].ranking_method_key
    for value in (first, second):
        assert _observation(value).observation_id.qualified not in selection.ranking_method_key
    for series_id in (
        first_net_force.series.series_id,
        second_net_force.series.series_id,
    ):
        assert series_id.qualified not in selection.ranking_method_key
    assert "ranking-mechanics-a" not in selection.ranking_method_key
    assert "ranking-mechanics-b" not in selection.ranking_method_key


def test_extreme_selection_retains_distinct_ranking_observations() -> None:
    candidate_a = _bind(_phase("distinct-candidate-a", _RES49_FIRST_TRACE), "a")
    candidate_b = _bind(_phase("distinct-candidate-b", _RES49_SECOND_TRACE), "b")
    ranking_a = _bind(_phase("distinct-ranking-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("distinct-ranking-b", _RES49_SECOND_TRACE), "b")
    candidate_set = _candidate_set((candidate_a, candidate_b))
    eligibility = evaluate_trial_eligibility(candidate_set, (candidate_a, candidate_b))
    assert not isinstance(eligibility, RefusalResult)
    selection = select_trials(
        candidate_set,
        eligibility,
        selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
        ranking_observations=(ranking_a, ranking_b),
        ranking_metric=ranking_a.observation.identity.semantic.metric_definition,
        ranking_method=ranking_a.observation.identity.processing.registered_operation,
        ranking_direction=TrialSelectionDirection.MAXIMIZE,
        tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
    )
    assert isinstance(selection, TrialSelectionDecision)
    assert selection.ranking_observation_ids == (
        ranking_a.observation.observation_id,
        ranking_b.observation.observation_id,
    )


def test_ranking_selection_refuses_material_method_mismatches() -> None:
    baseline = _bind(
        _phase("ranking-method-baseline", _RES49_FIRST_TRACE, onset_search_start_index=4),
        "a",
    )
    for changed in (
        _bind(
            _phase("ranking-method-onset", _RES49_SECOND_TRACE, onset_search_start_index=5),
            "b",
        ),
        _bind(
            _phase("ranking-method-takeoff", _RES49_SECOND_TRACE, takeoff_search_start_index=8),
            "b",
        ),
        _bind(
            _phase(
                "ranking-method-timebase",
                _RES49_SECOND_TRACE,
                timebase=RegularTimebase(500.0),
            ),
            "b",
        ),
        _bind(
            _phase(
                "ranking-method-loading",
                _RES49_SECOND_TRACE,
                external_loading="stable-attached-supported-load",
            ),
            "b",
        ),
    ):
        candidate_set = _candidate_set((baseline, changed))
        eligibility = evaluate_trial_eligibility(candidate_set, (baseline, changed))
        assert not isinstance(eligibility, RefusalResult)
        result = select_trials(
            candidate_set,
            eligibility,
            selection_rule=CMJ_SELECT_EXTREME_BY_REGISTERED_METRIC_V1,
            ranking_observations=(baseline, changed),
            ranking_metric=baseline.observation.identity.semantic.metric_definition,
            ranking_method=baseline.observation.identity.processing.registered_operation,
            ranking_direction=TrialSelectionDirection.MAXIMIZE,
            tie_policy=CMJ_TIE_EARLIEST_DECLARED_CANDIDATE_V1,
        )
        _assert_refusal(result, RefusalReasonCode.RANKING_METRICS_NOT_COMPARABLE)


def test_session_summary_comparability_retains_full_ranking_method_identity() -> None:
    def make_summary(prefix: str, onset_search_start_index: int) -> SessionAggregationResult:
        ranking_a = _bind(
            _phase(
                f"{prefix}-ranking-a",
                _RES49_FIRST_TRACE,
                onset_search_start_index=onset_search_start_index,
            ),
            "a",
        )
        ranking_b = _bind(
            _phase(
                f"{prefix}-ranking-b",
                _RES49_SECOND_TRACE,
                onset_search_start_index=onset_search_start_index,
            ),
            "b",
        )
        target_a = _bind(
            _phase(
                f"{prefix}-target-a",
                _RES49_FIRST_TRACE,
                CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
            ),
            "a",
        )
        target_b = _bind(
            _phase(
                f"{prefix}-target-b",
                _RES49_SECOND_TRACE,
                CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
            ),
            "b",
        )
        result = project_selected_trial(
            _extreme_selection((ranking_a, ranking_b)),
            (target_a, target_b),
            output_observation_id=InstanceIdentifier("observation", f"{prefix}-summary"),
        )
        assert isinstance(result, SessionAggregationResult)
        return result

    left = make_summary("ranking-bridge-left", 4)
    right = make_summary("ranking-bridge-right", 5)
    comparison = compare_cmj_session_summaries(
        left,
        right,
        claim="compare summaries with different ranking detector parameters",
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SESSION_RANKING_METHOD_MISMATCH.value in comparison.reason_codes


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


def test_extreme_selection_preserves_ranking_and_target_lineage() -> None:
    ranking_a = _bind(_phase("lineage-ranking-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("lineage-ranking-b", _UNIQUE_TRACE), "b")
    ranking_c = _bind(_phase("lineage-ranking-c", _RES49_SECOND_TRACE), "c")
    selection = _extreme_selection((ranking_a, ranking_b, ranking_c))
    target_b = _bind(
        _phase(
            "lineage-target-b",
            _RES49_SECOND_TRACE,
            CMJPhaseMetric.PROPULSION_NET_VERTICAL_IMPULSE,
        ),
        "b",
    )
    result = project_selected_trial(
        selection,
        (target_b,),
        ranking_observations=(ranking_a, ranking_b, ranking_c),
        output_observation_id=InstanceIdentifier("observation", "lineage-result"),
    )
    assert isinstance(result, SessionAggregationResult)
    provenance = result.observation.provenance
    session_run = next(
        run
        for run in provenance.processing_runs
        if run.output_entity_id == result.observation.observation_id
    )
    ranking_values = (ranking_a, ranking_b, ranking_c)
    source_observation_ids = tuple(_observation(value).observation_id for value in ranking_values)
    source_observation_ids += (target_b.observation.observation_id,)
    for observation_id in source_observation_ids:
        assert (
            sum(
                edge.from_id == observation_id.qualified
                and edge.to_id == session_run.processing_run_id.qualified
                and edge.relation is LineageRelation.DERIVED_FROM
                for edge in provenance.lineage_edges
            )
            == 1
        )
    source_artifact_ids = {
        artifact.artifact_id
        for value in (*ranking_values, target_b)
        for artifact in _observation(value).provenance.source_artifacts
    }
    source_acquisition_ids = {
        acquisition.acquisition_id
        for value in (*ranking_values, target_b)
        for acquisition in _observation(value).provenance.acquisitions
    }
    source_run_ids = {
        run.processing_run_id
        for value in (*ranking_values, target_b)
        for run in _observation(value).provenance.processing_runs
    }
    source_evidence = {
        evidence.reference.stable_id
        for value in (*ranking_values, target_b)
        for evidence in _observation(value).provenance.evidence_references
    }
    assert source_artifact_ids <= {item.artifact_id for item in provenance.source_artifacts}
    assert source_acquisition_ids <= {item.acquisition_id for item in provenance.acquisitions}
    assert source_run_ids <= {item.processing_run_id for item in provenance.processing_runs}
    assert source_evidence <= {
        evidence.reference.stable_id for evidence in provenance.evidence_references
    }
    assert any(
        edge.from_id == session_run.processing_run_id.qualified
        and edge.to_id == result.observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in provenance.lineage_edges
    )

    restored = from_canonical_json(canonical_json(result), SessionAggregationResult)
    assert restored == result
    assert canonical_hash(restored) == canonical_hash(result)


def test_shared_ranking_and_target_provenance_is_deduplicated() -> None:
    ranking_a = _bind(_phase("dedupe-ranking-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("dedupe-ranking-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((ranking_a, ranking_b))
    result = project_selected_trial(
        selection,
        (ranking_a, ranking_b),
        output_observation_id=InstanceIdentifier("observation", "dedupe-result"),
    )
    assert isinstance(result, SessionAggregationResult)
    provenance = result.observation.provenance
    assert len(provenance.source_artifacts) == len(
        {item.artifact_id for item in provenance.source_artifacts}
    )
    assert len(provenance.acquisitions) == len(
        {item.acquisition_id for item in provenance.acquisitions}
    )
    assert len(provenance.processing_runs) == len(
        {item.processing_run_id for item in provenance.processing_runs}
    )
    session_run = next(
        run
        for run in provenance.processing_runs
        if run.output_entity_id == result.observation.observation_id
    )
    assert (
        sum(
            edge.from_id == ranking_a.observation.observation_id.qualified
            and edge.to_id == session_run.processing_run_id.qualified
            and edge.relation is LineageRelation.DERIVED_FROM
            for edge in provenance.lineage_edges
        )
        == 1
    )


def test_selection_rejects_a_forged_extreme_without_ranking_provenance() -> None:
    ranking_a = _bind(_phase("missing-ranking-provenance-a", _RES49_FIRST_TRACE), "a")
    ranking_b = _bind(_phase("missing-ranking-provenance-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((ranking_a, ranking_b))
    with pytest.raises(ValueError, match="ranking authority provenance"):
        replace(selection, ranking_provenance=())


def test_select_all_legacy_wire_decode_explicitly_supplies_additive_fields() -> None:
    first = _bind(_phase("select-all-v3-a"), "a")
    second = _bind(_phase("select-all-v3-b"), "b")
    selection = _select_all((first, second))
    envelope = json.loads(canonical_json(selection))
    for field_name in ("ranking_method_key", "ranking_provenance", "ranking_authority"):
        del envelope["payload"][field_name]
    restored = from_canonical_json(json.dumps(envelope), TrialSelectionDecision)
    assert restored == selection
    assert restored.ranking_method_key is None
    assert restored.ranking_provenance == ()
    assert restored.ranking_authority == ()
    assert SERIALIZATION_VERSION == 3


@pytest.mark.parametrize(
    "present_fields",
    (
        ("ranking_method_key",),
        ("ranking_provenance",),
        ("ranking_authority",),
        ("ranking_method_key", "ranking_provenance"),
        ("ranking_method_key", "ranking_authority"),
        ("ranking_provenance", "ranking_authority"),
    ),
)
def test_partial_res50_ranking_fields_are_not_legacy(
    present_fields: tuple[str, ...],
) -> None:
    first = _bind(_phase("partial-modern-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("partial-modern-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    envelope = json.loads(canonical_json(selection))
    for field_name in {"ranking_method_key", "ranking_provenance", "ranking_authority"} - set(
        present_fields
    ):
        del envelope["payload"][field_name]

    with pytest.raises(ValueError, match="present together"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)


def test_pre_res50_extreme_v3_wire_is_readable_but_not_aggregation_authority() -> None:
    first = _bind(_phase("legacy-extreme-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("legacy-extreme-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    restored = _legacy_selection(selection)

    assert restored.selected_trial_ids == selection.selected_trial_ids
    assert restored.ranking_provenance == ()
    assert restored.ranking_authority == ()
    assert restored.ranking_method_key is not None
    assert restored.ranking_method_key.startswith("legacy-res40:")
    refused = project_selected_trial(restored, (first, second))
    _assert_refusal(refused, RefusalReasonCode.RANKING_METRIC_REQUIRED)


def test_legacy_ranking_authority_cannot_be_escalated() -> None:
    first = _bind(_phase("legacy-escalation-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("legacy-escalation-b", _RES49_SECOND_TRACE), "b")
    modern = _extreme_selection((first, second))
    legacy = _legacy_selection(modern)

    with pytest.raises(ValueError, match="legacy ranking identity"):
        replace(legacy, ranking_provenance=modern.ranking_provenance)
    with pytest.raises(ValueError, match="legacy ranking identity"):
        replace(legacy, ranking_authority=modern.ranking_authority)
    with pytest.raises(ValueError, match="ranking observation authority"):
        replace(legacy, ranking_method_key=modern.ranking_method_key)
    with pytest.raises(ValueError, match="legacy ranking identity"):
        replace(modern, ranking_method_key="legacy-res40:forged")


def test_deserialized_extreme_decision_recomputes_its_winner() -> None:
    first = _bind(_phase("deserialize-winner-a", _RES49_FIRST_TRACE), "a")
    second = _bind(_phase("deserialize-winner-b", _RES49_SECOND_TRACE), "b")
    selection = _extreme_selection((first, second))
    wrong_trial = (
        second.observation.context.trial_id
        if selection.selected_trial_ids[0] == first.observation.context.trial_id
        else first.observation.context.trial_id
    )
    assert wrong_trial is not None
    envelope = json.loads(canonical_json(selection))
    envelope["payload"]["selected_trial_ids"] = [json.loads(canonical_json(wrong_trial))["payload"]]
    with pytest.raises(ValueError, match="invalid|winner"):
        from_canonical_json(json.dumps(envelope), TrialSelectionDecision)

    altered_values = json.loads(canonical_json(selection))
    altered_values["payload"]["ranking_values"][0] += 0.001
    with pytest.raises(ValueError, match="invalid"):
        from_canonical_json(json.dumps(altered_values), TrialSelectionDecision)


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
    assert left.selection_decision.ranking_method_key is None
    assert right.selection_decision.ranking_method_key is None
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


def test_legacy_ranking_summaries_are_comparability_insufficient() -> None:
    left_first = _bind(_phase("legacy-summary-left-a", _RES49_FIRST_TRACE), "a")
    left_second = _bind(_phase("legacy-summary-left-b", _RES49_SECOND_TRACE), "b")
    right_first = _bind(_phase("legacy-summary-right-a", _RES49_FIRST_TRACE), "c")
    right_second = _bind(_phase("legacy-summary-right-b", _RES49_SECOND_TRACE), "d")
    left_modern = project_selected_trial(
        _extreme_selection((left_first, left_second)),
        (left_first, left_second),
        output_observation_id=InstanceIdentifier("observation", "legacy-summary-left"),
    )
    right_modern = project_selected_trial(
        _extreme_selection((right_first, right_second)),
        (right_first, right_second),
        output_observation_id=InstanceIdentifier("observation", "legacy-summary-right"),
    )
    assert isinstance(left_modern, SessionAggregationResult)
    assert isinstance(right_modern, SessionAggregationResult)
    left_legacy = _legacy_summary(left_modern)
    right_legacy = _legacy_summary(right_modern)

    legacy_comparison = compare_cmj_session_summaries(
        left_legacy,
        right_legacy,
        claim="compare legacy extreme summaries",
    )
    assert legacy_comparison.state is ComparabilityState.INSUFFICIENT_INFORMATION
    assert ComparabilityReasonCode.MISSING_METADATA.value in legacy_comparison.reason_codes
    assert (
        ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED.value in legacy_comparison.reason_codes
    )
    assert legacy_comparison.decided_by is ComparabilityDecisionSource.UNRESOLVED
    assert legacy_comparison.rule_reference is None
    assert "full RES-50 ranking method semantic identity" in legacy_comparison.missing_information
    assert "ranking observation authority/provenance" in legacy_comparison.missing_information

    legacy_modern_comparison = compare_cmj_session_summaries(
        left_legacy,
        right_modern,
        claim="compare legacy and modern extreme summaries",
    )
    assert legacy_modern_comparison.state is ComparabilityState.INSUFFICIENT_INFORMATION
    assert legacy_modern_comparison.decided_by is ComparabilityDecisionSource.UNRESOLVED

    modern_comparison = compare_cmj_session_summaries(
        left_modern,
        right_modern,
        claim="compare modern extreme summaries",
    )
    assert modern_comparison.state is ComparabilityState.COMPARABLE


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
