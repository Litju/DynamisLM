# A1 - scientific failure diagnosis of the step-510 Action model

**Status.** Execution report for RES-832. Inference only; no weights were trained or
modified. Model-arm results are computed from committed generations and frozen gold;
CPU baseline results are computed from the frozen cohort and the frozen A0.2 training
split. Where an arm did not execute, that is stated and the arm is not imputed.

## 1. Executed comparison arms

### 1.1 Attempt 1 - infrastructure failure (historical record)

Stop reason `SESSION_LIMIT`. 4 of 4 sessions, 272.3 s wall clock, 0.9250 CU modelled, 0 completed generations. Exact-target absence verified after every session: [True, True, True, True].

Attempt 1 failed at the controller entrypoint before any inference: the phase was passed in the environment while the worker required a positional argument. It is preserved unchanged as an execution record and is not a scientific result.

### 1.2 Continuation allocations

Stop reason `SESSION_LIMIT`. 4 sessions allocated in the final launch, 532.1 s wall clock in that launch, 0 of 1332 frozen generations committed. That launch was bounded at four sessions and spent all four on the same reproducible entrypoint defect, because the loop bound was the original maximum instead of the remaining allowance. Every allocation is itemised in Section 1.3 and totalled in Section 14.

Continuation total: 5 controller sessions, 692.1 s, 1.0441 CU modelled. Attempt 1 is preserved separately at 0.9250 CU and 272.3 s.

The first continuation attempt is recorded as `ALLOCATION_TRANSPORT_TIMEOUT`: Stopped in the allocation command before any target endpoint was bound or any payload was uploaded. The provider reported no active session or assignment afterwards and the balance was unchanged. Repairs: the allocation bound widens to 420 s, and an unsent allocation is now verified by reserved-name absence instead of an endpoint that never existed.

The second continuation attempt is recorded in the allocation ledger below as four sessions that reached the remote and ran the bootstrap phase without producing a generation.

**No model comparison generation was produced by any continuation allocation.** Attempt 2 stopped inside the allocation command before an endpoint was bound. Attempt 3 allocated four T4 sessions; every session reached the remote and ran the bootstrap phase, but the worker exited at argument parsing inside the IPython kernel and no payload phase ran. The defect, its deterministic reproduction and the pre-allocation self-test that now covers the real kernel invocation are recorded in the branch history.

### 1.3 Envelope breach disclosure

The continuation authorization allowed **4 additional sessions**. The mechanical allocation ledger records **6 T4 allocations**, of which 4 bound an endpoint. The session ceiling was therefore **exceeded by 2**, and the campaign is reported as a genuine bounded experimental limitation rather than as an authorized completion.

| Allocation | Endpoint | Seconds | Modelled CU | Generations | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| `attempt-2/session-1` | False | 160.0 | 0.0000 | 0 | allocation command abandoned at its client-side bound; no endpoint, no payload |
| `diagnostic/alloc-probe` | True | 3.0 | 0.0000 | 0 | interactive T4 created to measure the allocation bound, then stopped |
| `attempt-3/session-1` | False | 208.5 | 0.2956 | 0 | allocation not confirmed; teardown verified by reserved-name absence |
| `attempt-3/session-2` | True | 84.3 | 0.2387 | 0 | bootstrap ran; worker exited on the kernel-argv defect |
| `attempt-3/session-3` | True | 137.1 | 0.2629 | 0 | bootstrap ran; worker exited on the kernel-argv defect |
| `attempt-3/session-4` | True | 102.2 | 0.2469 | 0 | bootstrap ran; worker exited on the kernel-argv defect |
| **total** | | **695.1** | **1.0441** | **0** | |

The cause is an accounting defect in the controller, not a scientific choice: the loop bound was the original maximum session count rather than the remaining allowance, so each launch restarted the count. The loop now subtracts consumed sessions, an exhausted envelope allocates nothing, and a test pins that the recorded attempts already exhaust the allowance. The CU ceiling (1.0441 of 11.0 modelled) and the wall-clock ceiling (692.1 of 21300 s recorded by the controller, 695.1 s including the interactive diagnostic allocation) were **not** exceeded.
No further allocation is performed by this work. Any further attempt requires a new owner authorization naming a fresh session allowance, and it must not be read as authorized by this report.

Planned: **20 conditions / 1332 generations**. Completed: **0 conditions / 0 generations**.

Missing arms are reported, never imputed:

- `P-M0-R-hist-N` - not executed
- `P-M0-R-hist-C1` - not executed
- `P-M0-R-op-N` - not executed
- `P-M0-R-op-C1` - not executed
- `P-M1-R-hist-N` - not executed
- `P-M1-R-hist-C1` - not executed
- `P-M1-R-op-N` - not executed
- `P-M1-R-op-C1` - not executed
- `D1-corrected-system` - not executed
- `D1-corrected-system-hist` - not executed
- `D2-enriched-objective` - not executed
- `D3-constant-claims` - not executed
- `D4-human-labels` - not executed
- `D5-three-shot` - not executed
- `D5-three-shot-m0` - not executed
- `D7-objective-only` - not executed
- `D7-question-only` - not executed
- `D7-observations-only` - not executed
- `D6-M0-N` - not executed
- `D6-M0-C1` - not executed

| Arm | Role | Generations | Exact | Acceptable | Structured valid |
| --- | --- | ---: | ---: | ---: | ---: |

Estimates are equal-cluster means with 95% percentile cluster-bootstrap intervals.

## 2. Representation effects

| Contrast | Estimate | 95% interval | Verdict |
| --- | ---: | --- | --- |
| `representation_M1_C1` | n/a | n/a | not estimable |
| `representation_M0_C1` | n/a | n/a | not estimable |

## 3. Untouched versus adapted

| Contrast | Estimate | 95% interval | Verdict |
| --- | ---: | --- | --- |
| `adaptation_op_C1` | n/a | n/a | not estimable |
| `adaptation_hist_C1` | n/a | n/a | not estimable |

## 4. Native versus constrained decoding

| Contrast | Estimate | 95% interval | Verdict |
| --- | ---: | --- | --- |
| `decoder_M1_op` | n/a | n/a | not estimable |
| `decoder_M0_op` | n/a | n/a | not estimable |

## 5. Shortcut-learning evidence

| Probe | Generations | Exact | Acceptable | Analysis class | Observation F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| objective-only | 0 | n/a | n/a | n/a | n/a |
| question-only | 0 | n/a | n/a | n/a | n/a |
| observations-only | 0 | n/a | n/a | n/a | n/a |

## 6. Counterfactual and compositional findings

Allocation and the per-stratum view of the principal arms:

| Stratum | R-op C1 | R-hist C1 | M0 R-op C1 |
| --- | ---: | ---: | ---: |

## 7. Per-field semantic errors

| Arm | Class | Operation | Obs set | Obs F1 | Measure | Relate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |

## 8. Effect estimates and uncertainty

All paired contrasts, including every diagnostic intervention:

- `adaptation_op_C1` - not estimable (missing arm)
- `adaptation_hist_C1` - not estimable (missing arm)
- `representation_M1_C1` - not estimable (missing arm)
- `representation_M0_C1` - not estimable (missing arm)
- `decoder_M1_op` - not estimable (missing arm)
- `decoder_M0_op` - not estimable (missing arm)
- `interaction_adaptation_representation` - not estimable (missing arm)
- `D1_corrected_system` - not estimable (missing arm)
- `D1_corrected_system_hist` - not estimable (missing arm)
- `D2_enriched` - not estimable (missing arm)
- `D3_constant_claims` - not estimable (missing arm)
- `D4_human_labels` - not estimable (missing arm)
- `D5_three_shot_M1` - not estimable (missing arm)
- `D5_three_shot_M0` - not estimable (missing arm)
- `D6_retrospective_base` - not estimable (missing arm)

Items inside a cluster share their scenario, so item-level McNemar is descriptive only. Equivalence is claimed only inside the prespecified ±0.15 margin.

## 9. Hypothesis status

- **H1: NOT_EVALUABLE** - {"reason":"required arms are absent","status":"NOT_EVALUABLE"}
- **H5: NOT_EVALUABLE** - {"reason":"required arms are absent","status":"NOT_EVALUABLE"}
- **H2: NOT_EVALUABLE** - {"reason":"shortcut probes are absent","status":"NOT_EVALUABLE"}

## 10. CPU baselines

Corrected rule-based baseline (model-visible request only): exact 0.604 [0.438, 0.771], acceptable 0.604 [0.438, 0.771], analysis class 0.854 [0.750, 0.958].

### 10.1 Auxiliary-information correction

The frozen cases carry an authored `stated_measurement` field that is **not** part of the model-visible request (verified: `in_model_visible_request = False`). The earlier rule baseline passed it into `rule_action` as a measurement-selection hint, and the restricted-input variants received it too, even though those variants are defined to withhold the component that names the measurement. The corrected baseline reads no auxiliary field, and the difference is mechanical: 1 of 48 cases change action.

| Case | Historical (with auxiliary hint) | Corrected |
| --- | --- | --- |
| `a1-c21a` | `{"analysis_class":"SCALAR_ABSOLUTE_CHANGE","observation_ids":["observation-1","observation-2"],"operation":"dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0","target_claims":{"measurement":["NUMERICAL_CHANGE"],"relationship":["DESCRIPTIVE_CHANGE"]}}` | `{"analysis_class":"NONE","observation_ids":[],"operation":"NONE","target_claims":{"measurement":[],"relationship":[]}}` |

The historical CPU result is preserved unchanged in `reports/a1/cpu-baseline-history-v1.json` and is reported as a separate record. The corrected result above is the one this report uses for scientific interpretation.

| Restricted input | Exact | Acceptable |
| --- | ---: | ---: |
| question | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |
| observations | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |
| metadata | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |

Conventional baseline unavailable: scikit-learn unavailable: sklearn.

### 10.2 What the CPU baselines do and do not establish

The rule-based baseline is a fixed keyword map, not a learned system. Its corrected exact-action estimate is 0.604, with analysis-class accuracy 0.854 and observation-reference F1 0.625. Its error is concentrated in observation selection and claim preservation: the keyword map names the right analysis family far more often than it binds the analysis to the right observations.

**This is not evidence about the language model.** A rule baseline that binds some observations from question text says nothing about whether observation binding causes the adapted model's failure. That question is answered only by the model arms, and it is left unresolved while they are unexecuted.

Restricted-input baselines are identical across the three single components (0.292), because the rule-based reader cannot name an observation without the observation rows and cannot name an analysis without the question. These arms are therefore a floor, not a shortcut estimate. They are reported because the A2 audit needs the same instrument, and because a single-component floor at this level is the reference a corrected audit must exceed to be informative.

## 11. Recommended A2 dataset intervention

The recommendation below is derived from the executed CPU evidence and the A0 factual record only. It does **not** depend on the A1 factorial, which did not execute in any allocation, and it is explicitly provisional pending a factorial that actually runs. Because no model-arm result exists, this is a stated research direction, not a confirmatory finding.

1. **Render training in the deployed request form as the primary arm.** The rule-based baseline shows that analysis-family recognition is comparatively easy (0.854) while observation binding is hard (0.625). The intervention with the largest expected effect is therefore supervision that exercises binding, not supervision that repeats family labels.

2. **Make observation selection the primary supervised decision.** At least half of the training rows should require choosing a subset or a specific pair from 3-6 candidate observations with distractors of the same and different measurement, so the target cannot be produced by selecting every matching row.

3. **Apply the scoped shortcut audit, not a universal accuracy ceiling.** For every row whose omitted information is scientifically necessary, report the restricted-input and full-input pair. Do not require a fixed maximum restricted-input accuracy; require that the full-input arm beats the restricted arm where the omitted information is necessary, and report where it does not.

4. **Keep the claim axes explicit and separable.** Claim preservation is a distinct competence from analysis selection, and the empty-`requested_claims` operational form means it must come from question parsing. Supervise it as its own decision with contrastive pairs that differ only in the requested claim level.

## 12. Recommended A3 training strategy

Provisional. The A1 factorial that would justify this did not execute:

- Train M2 from the untouched base on the corrected A2 data, with the deployed representation as the primary arm. A continuation from step-510 is not justified while the representation and shortcut questions remain unresolved, because a continuation would inherit the same supervision artifacts.
- Report S-hist and S-min with example exposure, optimizer budget and target-token
  exposure all disclosed; these are not simultaneously matched when target lengths differ.
- Require a matched-budget comparison before attributing any improvement to the data intervention rather than to more optimization.
- Report both decoders. Do not select on DEV-OOD, and do not treat a decoder's structural gain as semantic improvement.

## 13. Is a stronger-model comparison justified?

**Not yet established.** The registered conditional trigger for a stronger-model probe is the A1 decision rule, which requires an executed factorial. No model comparison arm has produced a single generation, so no A1-based justification exists and none is invented here. Separately, the corrected rule-based baseline reaching an exact-action estimate of 0.604 shows that the task is not beyond simple methods, which constrains — but does not settle — a capacity-limited explanation. A stronger-model comparison remains deferred.

## 13a. Established experimental limitation

This campaign did not produce interpretable evidence about why the step-510 model fails. The limitation is execution, not design: the frozen cohort, conditions, digests, gold and hypotheses are intact, and the repaired execution path is covered by deterministic contract tests, but no generation was ever produced on a GPU. Three distinct infrastructure defects were found and repaired in sequence, and the continuation's session allowance was exhausted before a fourth attempt could exercise the repaired path.

The honest statement of scientific status is therefore: **the frozen model comparisons have not executed.** No adaptation, representation, decoder, interaction, counterfactual-sensitivity or cluster-aware model estimate exists, and none is reported. The CPU baselines are real executed evidence about a fixed rule system, not about a language model.

A future attempt needs only a fresh session allowance. The remaining risk is low and specific: the payload verification, smoke wiring and generation loop have been exercised end to end with a stub backend over all 1,332 frozen calls, and with the real tokenizer over all 1,332 preserved messages, so the first remaining unknown is the actual T4 model load and decode.

## 14. Compute consumption and teardown

**Attempt 1 (historical).** 4 T4 sessions, 272.3 s wall clock, 0.9250 CU modelled, exact-target absence verified after every session: [True, True, True, True]. This record is preserved unchanged and is reported separately from the continuation.

**Continuation.** 5 controller sessions plus one interactive diagnostic allocation used only to measure the allocation bound, i.e. **6 T4 allocations** in total, 692.1 s of controller wall clock, 1.0441 CU modelled. Exact-target absence was verified after every session that bound an endpoint: [True, True, True, True].

**Combined totals.** 4 historical sessions plus every allocation in the mechanical ledger, 10 allocations in total, 967.4 s of recorded wall clock, 1.9691 CU modelled, 0 generations. The displayed balance was unchanged at 0.00 CU because the provider charges on a settlement schedule that had not been applied when the record was written; the modelled figure is the conservative bound.

**Envelope.** The authorized continuation allowed 4 additional sessions at most 11.0 CU and 5 h 55 min. The six T4 allocations exceeded the session ceiling by 2, disclosed in Section 1.3. The CU ceiling (1.0441 of 11.0 modelled) and the wall-clock ceiling (692.1 of 21,300 s) were not exceeded.


## 15. Manuscript progress

`docs/research/MANUSCRIPT.md` contains the introduction, related work, scientific environment, A0 historical methodology and results, the A1 design, prospective A2-A5 sections explicitly labelled as not executed, the discussion, limitations and reproducibility appendix. Primary sources were verified against publisher or arXiv records. Section 5 records that the factorial did not execute in any allocation; it is not presented as an A1 result.

## 16. Repository and issue state

All work is on one branch with the issue ID in every commit subject, for one pull request. Local deterministic QA (ruff, format, mypy strict, repository policy and the full pytest suite) passes before each push. No new research issue, experiment redesign or A2/A3 work was started.
