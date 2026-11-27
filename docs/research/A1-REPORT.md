# A1 - scientific failure diagnosis of the step-510 Action model

**Status.** Execution report for RES-832. Inference only; no weights were trained or
modified. Model-arm results are computed from committed generations and frozen gold;
CPU baseline results are computed from the frozen cohort and the frozen A0.2 training
split. Where an arm did not execute, that is stated and the arm is not imputed.

## 1. Executed comparison arms

### 1.1 Campaign execution

**Stop reason: `SESSION_LIMIT`.** 4 of 4 authorized sessions were allocated in 272.3 s of wall clock, producing 0 completed generations. Modelled consumption was 0.9250 CU against a 12.0 CU cap, and the displayed balance fell by 0.01 CU. Exact-target absence was verified after every session: [True, True, True, True].

| Session | Seconds | Error | Target absent |
| ---: | ---: | --- | --- |
| 1 | 51.8 | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` | True |
| 2 | 58.4 | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` | True |
| 3 | 54.4 | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` | True |
| 4 | 107.7 | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` | True |

**No model comparison arm was executed.** Every session failed at the same controller entrypoint defect before any inference: the phase was passed in the environment while the worker required a positional argument, so the worker exited at argument parsing and the controller advanced to the next session on the same defect. The defect and its regression tests are recorded in commit `RES-832: fix the campaign entrypoint defect that consumed the session envelope`. The authorized envelope is exhausted; no additional session was attempted and none is authorized by this report.

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
- `D6-M0-N` - not executed
- `D6-M0-C1` - not executed
- `D7-objective-only` - not executed
- `D7-question-only` - not executed
- `D7-observations-only` - not executed

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

Rule-based: exact 0.583 [0.417, 0.750], acceptable 0.583 [0.417, 0.750], analysis class 0.833 [0.708, 0.938].

| Restricted input | Exact | Acceptable |
| --- | ---: | ---: |
| question | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |
| observations | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |
| metadata | 0.292 [0.125, 0.458] | 0.292 [0.125, 0.458] |

Conventional per-field TF-IDF logistic regression (fields: analysis_class, measurement, operation, relationship): exact 0.021 [0.000, 0.062], analysis class 0.146 [0.042, 0.271].
Conventional baseline with measurement identity masked: exact 0.021 [0.000, 0.062], analysis class 0.208 [0.083, 0.354].

### 10.1 What the CPU baselines do and do not establish

The rule-based baseline is a fixed keyword map, not a learned system. Its exact-action estimate is 0.583, with analysis-class accuracy 0.833 and observation-reference F1 0.604. Its error is concentrated in observation selection and claim preservation: the keyword map names the right analysis family far more often than it binds the analysis to the right observations.

The conventional per-field classifier is trained on the frozen A0.2 TRAIN split and evaluated on the A1 cohort. Its exact-action estimate is 0.021. This is expected and is itself a finding about the transfer problem: A0.2 supervision uses a different synthetic measurement namespace and a different comparator set, so a bag-of-ngrams model trained on it cannot bind A1's registry identities. Masking the identity strings raises analysis-class accuracy to 0.208 without improving exact match, which localises the failure to binding, not to recognising the analysis family.

Restricted-input baselines are identical across the three single components (0.292), because the rule-based reader cannot name an observation without the observation rows and cannot name an analysis without the question. These arms are therefore a floor, not a shortcut estimate. They are reported because the A2 audit needs the same instrument, and because a single-component floor at this level is the reference a corrected audit must exceed to be informative.

## 11. Recommended A2 dataset intervention

The recommendation below is derived from the executed CPU evidence and the A0 factual record only. It does **not** depend on the unexecuted A1 factorial, and it is explicitly provisional pending that factorial.

1. **Render training in the deployed request form as the primary arm.** The rule-based baseline shows that analysis-family recognition is comparatively easy (0.833) while observation binding is hard (0.604). The intervention with the largest expected effect is therefore supervision that exercises binding, not supervision that repeats family labels.

2. **Make observation selection the primary supervised decision.** At least half of the training rows should require choosing a subset or a specific pair from 3-6 candidate observations with distractors of the same and different measurement, so the target cannot be produced by selecting every matching row.

3. **Apply the scoped shortcut audit, not a universal accuracy ceiling.** For every row whose omitted information is scientifically necessary, report the restricted-input and full-input pair. Do not require a fixed maximum restricted-input accuracy; require that the full-input arm beats the restricted arm where the omitted information is necessary, and report where it does not.

4. **Keep the claim axes explicit and separable.** Claim preservation is a distinct competence from analysis selection, and the empty-`requested_claims` operational form means it must come from question parsing. Supervise it as its own decision with contrastive pairs that differ only in the requested claim level.

## 12. Recommended A3 training strategy

Provisional, and conditional on the A1 factorial that did not execute:

- Train M2 from the untouched base on the corrected A2 data, with the deployed representation as the primary arm. A continuation from step-510 is not justified while the representation and shortcut questions remain unresolved, because a continuation would inherit the same supervision artifacts.
- Report S-hist and S-min with example exposure, optimizer budget and target-token
  exposure all disclosed; these are not simultaneously matched when target lengths differ.
- Require a matched-budget comparison before attributing any improvement to the data intervention rather than to more optimization.
- Report both decoders. Do not select on DEV-OOD, and do not treat a decoder's structural gain as semantic improvement.

## 13. Is a stronger-model comparison justified?

**Not yet established.** The registered conditional trigger for a stronger-model probe is the A1 decision rule, which requires the executed factorial. With zero completed model arms, no A1-based justification exists. Separately, the rule-based baseline reaching an exact-action estimate of 0.583 shows that the task is not beyond simple methods, which weakens — but does not settle — the capacity-limited explanation. A stronger-model comparison remains deferred.

## 14. Compute consumption and teardown

Four T4 sessions were allocated and all four were torn down with exact-target absence verified. Modelled consumption 0.9250 CU; displayed balance delta 0.01 CU; wall clock 272.3 s. The aggregate stayed within the authorized 12.0 CU and 21600 s ceilings (`within_cap = True`). The session count reached the authorized maximum, so the envelope is exhausted.

## 15. Manuscript progress

`docs/research/MANUSCRIPT.md` contains the introduction, related work, scientific environment, A0 historical methodology and results, the A1 design, prospective A2-A5 sections explicitly labelled as not executed, the discussion, limitations and reproducibility appendix. Primary sources were verified against publisher or arXiv records. Section 5 is written against the A1 design and currently records that the factorial did not execute; it will be completed when the campaign runs.

## 16. Git, PR and Linear state

All work is on branch `work/res-832-a1-diagnosis`, one PR, with the issue ID in every commit subject. Local deterministic QA (ruff, format, mypy strict, repository policy, the full pytest suite) passes before each push. RES-833, RES-834 and RES-835 carry the prospective roadmap corrections as Linear comments; no new issues were created.
