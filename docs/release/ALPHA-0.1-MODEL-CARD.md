# DynamisLM-Action-3B-v0.1 — experimental model card

**Status: EXPERIMENTAL / NOT QUALIFIED FOR RELEASE.** The registered internal
evaluation returned `INTERNAL_NO_GO` on 26 November 2026. This card describes
the artifact and its measured limits; it does not claim a qualified or
independently validated model.

## Artifact identity

| Item | Value |
| --- | --- |
| Proposed name | `DynamisLM-Action-3B-v0.1` |
| Base model | `HuggingFaceTB/SmolLM3-3B` |
| Base revision | `a07cc9a04f16550a088caea529712d1d335b0ac1` |
| Adapter | frozen step-510 PEFT LoRA |
| Adapter weights SHA-256 | `7bda8c60c2e27206d60a41f7f454ecce721e46704e731b4f6c268d042572a6e7` |
| Release adapter config SHA-256 | `a694b6cf6929b48ac7a1be52871d3afe7620c77569d8133f17f6466720ac83b4` |
| Original adapter config SHA-256 | `fd308f182471b62d50032f774b41c56895d3979b5ac522eb5fa7228d8bc57f6e` |
| Bundle archive SHA-256 | `d0e6c2a34fdafde9ca7783e7cd540d2fcb8d285d5735139fea5f243f9219ddd3` |
| Training metadata SHA-256 | `1f3bcf6abe549d855ad89d32d54b9040af4be66ee81f3115f9c308852d1d11a4` |
| Evaluation binding SHA-256 | `da277638987032acad53243a65762787ddd3caf6804986a949a25048ccd25176` |
| Training source | `deb4793` / tree `ff9b6a3` |
| Training specification SHA-256 | `35713a1fbe91c73d78493c8a824659a9d82378d0b13cb85b53a37b09b8351d4d` |
| Training data | A0.2 synthetic TRAIN split, 2,800 rows, manifest `746cad1b…f2569` |
| Supervised target tokens | 385,600 |
| LoRA | rank 16, alpha 32, dropout 0.05, q/k/v/o projections |

The adapter is trained, not merged. Base weights are not redistributed.

## Intended use

Research on structured scientific-intent proposals over **packaged synthetic
scenarios** in football performance science. The model proposes a narrow V3
scientific action; deterministic Python code parses, admits, refuses, computes
and reports. The model is a specialised generative semantic parser and action
selector, not a general scientific reasoning model.

## Out of scope

Coaching, clinical, return-to-play, talent selection, real-athlete measurement,
causal explanation, practical or decision-meaningfulness claims, and any use
that treats a model proposal as a scientific result. The model does not
establish measurement validity, comparability, causality or practical
significance.

## Evaluation

Registered protocol: RES-773 v1 with the RES-827 v3 recorded-approval receipt.
Evidence class `INTERNAL_OWNER_ADJUDICATED`; independence `NONE`. Cohort: 48
synthetic clusters, 96 items, 12 clusters per stratum, 24 EXECUTE / 57 REFUSE /
15 ABSTAIN, 96/96 owner-accepted dispositions. Arms: native greedy N and
constrained C1, 96 items each, 192 real generations.

Overall decision: **`INTERNAL_NO_GO`**.

| Endpoint | C1 result | Status |
| --- | ---: | --- |
| Unauthorized dispatch | 0 / 96 | PASS |
| Execution coverage | 0 / 24 | NO_GO |
| Hazard refusal | 36 / 48 (75.0%) | NO_GO |
| Novel intent | 0 / 24 (0.0%) | NO_GO |
| Causal overreach | 20 / 24 (83.3%, lower 66.7%) | INCONCLUSIVE |
| Practical meaning | 10 / 24 (41.7%) | NO_GO |

Structured-output validity was 96/96 in both arms. N and C1 produced
byte-identical token IDs for all 96 items. The model collapsed to 27 distinct
outputs per arm, usually `analysis_class: SCALAR_ABSOLUTE_CHANGE` with
`operation: NONE`, or `analysis_class: NONE` with empty or overreaching claims.
No expected EXECUTE item selected the registered operation. No execution
occurred. The deterministic engine refused every proposal that lacked
sufficient authority, and no unauthorized dispatch occurred.

The principal failure is learned action selection under the release prompt.
A0.2 training rows carried template-written `objective`, `missing_evidence` and
`comparability_evidence`; the release prompt sends only the question,
observations and requested claims. Failure is present in the familiar-language
stratum as well as the novel-language stratum. The experiment has no untouched
foundation-model arm, so the causal contribution of LoRA fine-tuning is not
identified.

## Hardware and runtime

FP32, MATH SDPA, greedy decoding, EOS 128012, TF32 and autocast disabled.
Qualified CUDA profile: one Tesla T4, CUDA 13.0, CPython 3.13, torch
2.14.1+cu130, transformers 4.53.0, tokenizers 0.21.1, peft 0.16.0.
Measured peak CUDA reserved 13,438,550,016 bytes; peak host RSS 7,093,436,416
bytes; mean generation 7.88 s/call on T4. CPU FP32 is the shipped RES-430 path
at roughly 15 GB peak RSS and minutes per call.

## Known deficits

Constant-refusal collapse; failure to select the registered operation;
0/24 execution coverage; 0/24 novel intent; 75% hazard refusal; 41.7% practical
meaning; causal endpoint inconclusive; C1 identical to N; no foundation-model
ablation; synthetic and owner-adjudicated evidence only.

## Licensing

The adapter license decision is **not resolved** in the RES-772 bundle:
`distribution: LICENSE_DECISION_REQUIRED`, `publication_qualified: false`.
SmolLM3-3B is upstream Apache-2.0; its weights are not included and must not be
redistributed without checking the applicable upstream rights.
