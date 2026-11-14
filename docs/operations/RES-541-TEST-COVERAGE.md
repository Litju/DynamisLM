# RES-541 test coverage inventory

Each essential invariant below has one owning test (module `tests/test_res541_a02_v3_<module>.py`
unless a full path is given) in a required CI shard. The partition is
`scripts/test_shards.py`: `fast` (scientific, contract and unit regression),
`controller` (controller, safety and fault injection) and `integration` (expensive integration
and full-workload integrity). The required `ci` check passes only when every shard and the
mission-policy job succeed. No test is skipped or deselected to meet a time budget; the only
skips are environment-gated (no `torch`, no pinned offline tokenizer).

## Scientific authority (fast unless stated)

| Invariant | Owning test |
| --- | --- |
| Frozen V3 protocol bytes and identity claims refuse tampering | `decision::test_protocol_tampering_is_detected`, `protocol_binding::test_generated_semantics_pin_is_enforced` |
| Independent gold refuses a diverging generator | `generated_gold::test_load_protocol_refuses_a_generator_that_diverges_from_independent_gold` |
| Every generated example independently derived, none skipped | `generated_gold::test_every_generated_example_is_independently_derived_and_none_is_skipped` |
| Frozen decision rule scores a complete checkpoint on CPU | `worker::test_complete_run_scores_entirely_on_cpu` (integration) |
| Numerical acceptance threshold and kernel certificate | `automatic::test_qualified_numerical_kernel_certificate_matches_real_predecessor` (controller) |
| 306 preserved evaluations: sealed prefix kept, session 3 next, no retry | `baseline_successor::test_successor_preserves_prefix_starts_session3_and_cannot_retry` (controller) |
| Original spending ceiling carried forward, only remaining work priced | `baseline_successor::test_proposal_prices_only_remaining_work_and_preserves_original_ceiling` (controller) |
| FP32 adoption requires actual precision evidence | `execution::test_fp32_checkpoint_adoption_requires_actual_precision_evidence` (integration) |
| Cache qualification failure touches no protected held-out request | `execution::test_failed_cache_qualification_ends_the_campaign_before_any_protected_work` (integration) |

## Full-workload integrity (integration)

| Invariant | Owning test |
| --- | --- |
| **The one full-scale test:** 581 items exactly once, in order, nine packed sessions, reserve unused, ledger within cap, frozen scorer decision, 560 held-out records over 280 examples, identical to one uninterrupted run | `execution::test_nine_session_campaign_covers_every_item_exactly_once` |
| Torn writes across sessions resume to the complete, identical evidence | `execution::test_interrupted_sessions_resume_to_completion_and_score_on_cpu` |
| A new invocation after a torn write resumes exactly at the safe boundary | `execution::test_campaign_stops_at_a_torn_write_then_a_new_invocation_resumes` |
| One lost session is absorbed by the reserve and the run completes | `execution::test_one_lost_session_is_absorbed_by_the_reserve_and_the_run_still_completes` |
| Worker-level resume equals an uninterrupted run; torn tail discarded | `worker::test_interrupted_and_resumed_run_equals_uninterrupted_run`, `worker::test_torn_final_write_is_discarded_and_recovered` |
| Real archive prepare/work with a real bounded child | `bootstrap_integration::test_colab_archive_prepare_and_work_use_real_bounded_child` |

## Authorization and admission (controller unless stated)

| Invariant | Owning test |
| --- | --- |
| No allowance, expired allowance: no allocation | `execution::test_unauthorized_session_never_allocates`, `execution::test_expired_or_missing_allowance_allocates_nothing` (integration) |
| An allowance only tightens, never widens | `execution::test_allowance_can_only_tighten_never_widen_and_fails_closed` (integration) |
| Unadmitted or drifted source identity never allocates | `controller_qualification::test_unadmitted_source_binding_never_allocates`, `controller_qualification::test_ledger_with_different_source_identity_is_refused`, `execution::test_clean_source_drift_refuses_next_session` |
| A consumed session marker cannot be reused | `execution::test_session_marker_is_consumed_and_cannot_be_reused` (integration) |
| A pre-existing session with our exact name is never adopted | `execution::test_a_preexisting_session_with_the_exact_name_is_never_adopted` (integration) |
| Diagnostic needs both explicit owner decisions | `gpu_diagnostic::test_admission_requires_both_explicit_owner_decisions` |
| Session count and cumulative cap bound the campaign | `execution::test_two_lost_sessions_exhaust_the_allowance_before_completion`, `execution::test_allowance_cap_bounds_the_campaign_before_the_cap_is_exceeded` (integration) |

## Checkpoint corruption (controller unless stated)

| Invariant | Owning test |
| --- | --- |
| Corrupted, forked or partially downloaded checkpoints are never adopted | `controller_qualification::test_every_fault_is_safe_and_terminal[corrupted_checkpoint, forked_checkpoint, partial_checkpoint_download]` |
| Forged remote line, shorter remote, forged status binding, re-chained revision drift | `execution::test_forked_remote_checkpoint_is_rejected_and_local_evidence_kept`, `execution::test_merge_rejects_shorter_remote_evidence`, `execution::test_status_binding_forgery_rejects_checkpoint`, `execution::test_revision_drift_in_remote_evidence_is_rejected_and_local_evidence_survives` (integration) |

## Stop and teardown failures (controller unless stated)

| Invariant | Owning test |
| --- | --- |
| A failed stop escalates in bounded rounds and keeps the watchdog armed | `supervision::test_failed_stop_during_blocked_work_escalates_and_keeps_watchdog_armed` |
| A stop that returns true or raises is not proof of absence | `supervision::test_stop_returning_true_is_not_proof_of_absence`, `supervision::test_stop_exception_is_recorded_and_never_treated_as_success` |
| Absence is verified before the watchdog is disarmed | `supervision::test_delayed_provider_termination_is_verified_before_disarm` |
| An unverified target blocks every later run | `supervision::test_unverified_target_leaves_a_marker_that_blocks_every_later_run` |
| A complete checkpoint cannot erase a failed teardown; its cost stays unknown | `execution::test_complete_checkpoint_cannot_erase_failed_teardown_on_reentry`, `execution::test_failed_teardown_cost_remains_unknown_after_late_cleanup` (integration) |
| A failed emergency stop or uncertain cost stays terminal on re-invocation | `controller_qualification::test_every_fault_is_safe_and_terminal[emergency_stop_fails, cost_uncertain_after_termination]` |

## Pricing and cost (controller unless stated)

| Invariant | Owning test |
| --- | --- |
| Missing, invalid or unverified pricing blocks the first allocation | `cost_ledger::test_missing_or_invalid_cost_policy_blocks_the_first_allocation`, `cost_ledger::test_unverified_pricing_component_blocks_allocation` |
| Forged, malformed, rounded or untrustworthy accounting never lowers the guard | `cost_ledger::test_forged_or_malformed_accounting_never_lowers_the_guard`, `cost_ledger::test_cumulative_guard_cannot_be_defeated_by_rounded_balances`, `cost_ledger::test_untrustworthy_ending_balance_is_unknown_and_blocks_allocation` |
| An observed price failure prevents all model preparation | `gpu_diagnostic::test_observed_price_failure_prevents_all_model_preparation` |
| A cost overrun is recorded and blocks later invocations | `execution::test_cost_overrun_is_recorded_and_blocks_a_later_invocation` (integration) |

## State transitions and liveness (controller unless stated)

| Invariant | Owning test |
| --- | --- |
| Every anomaly stops the campaign with no retry, exact target only | `execution::test_every_anomaly_stops_the_campaign_without_a_retry` (integration) |
| Healthy sessions chain to completion with no false anomaly; none after completion | `controller_qualification::test_liveness_healthy_sessions_chain_to_the_complete_checkpoint` |
| Normal teardown admits the next session cleanly | `lifecycle_monitoring::test_normal_teardown_is_followed_by_a_clean_next_session_admission` |
| Expected teardown-window inventory mismatch is not a false failure | `lifecycle_monitoring::test_inventory_mismatch_during_allocation_is_not_a_false_terminal_failure` |
| Stale monitor heartbeat or dead watchdog stops paid work | `supervision::test_no_work_when_the_monitor_heartbeat_is_stale`, `supervision::test_a_watchdog_dying_during_paid_work_interrupts_it_and_tears_down` |

## Genuine subprocess and watchdog behavior (controller)

| Invariant | Owning test |
| --- | --- |
| A real watchdog subprocess takes over after unverified absence, bounded rounds | `controller_qualification::test_real_watchdog_subprocess_takes_over_and_is_recorded` |
| An independent watchdog survives parent death | `live_safety::test_independent_watchdog_survives_parent_death` |
| A real child's status overrules a successful CLI exit | `preparation::test_real_child_status_overrules_successful_cli` |

## Three historical controller safety defects (controller)

| Defect (independent review on `b60d0e0`) | Owning executable adversarial test |
| --- | --- |
| Child worker deadline used the unreduced parent timeout | `remote::test_work_child_receives_its_actual_timeout_after_outer_setup`, `preparation::test_actual_setup_time_limits_work_and_preserves_cleanup` |
| Monitoring gaps during allocation and transfers | `preparation::test_cost_monitor_covers_all_paid_session_phases` |
| Watchdog started teardown at the session limit | `live_safety::test_stalled_successor_watchdog_reserves_time_for_slow_teardown` |

## Test-harness seams

| Invariant | Owning test |
| --- | --- |
| Reused protocol verification never answers for different bytes or code | `protocol_binding::test_reused_protocol_verification_is_invalidated_by_in_place_tampering` |
| Every test module is in exactly one required shard; required `ci` needs every job | `tests/test_ci_determinism.py::test_required_ci_shards_partition_every_test_module_exactly_once`, `tests/test_ci_determinism.py::test_required_ci_check_needs_every_job_and_every_shard` |
