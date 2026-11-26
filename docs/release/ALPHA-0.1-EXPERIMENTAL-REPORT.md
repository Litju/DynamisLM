# DynamisLM-Action-3B-v0.1 — experimental evaluation report

**Decision: `INTERNAL_NO_GO`.** Completed 26 November 2026. The checkpoint is
preserved as an experimental artifact. It is not a qualified release and must
not be published as one.

## Research question

Can the frozen step-510 action model select the correct scientific action,
observations and claim boundary over held-out synthetic football-performance
scenarios, and does the corrected C1 constrained decoder change its behaviour
relative to native greedy decoding, under the deterministic RES-70/RES-69
authority path?

## Artifact

- Base: `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1`.
- Adapter: frozen step-510 LoRA, rank 16, alpha 32, dropout 0.05, q/k/v/o.
- Trained on 2,800 synthetic A0.2 TRAIN rows, 385,600 supervised target tokens.
- Adapter weights `7bda8c60…a6e7`; bundle `d0e6c2a3…ddd3`.
- Runtime: FP32, MATH SDPA, greedy, EOS 128012, torch 2.14.1+cu130,
  transformers 4.53.0, peft 0.16.0, CPython 3.13.

## Design

- RES-773 v1 scientific protocol with the RES-827 v3 recorded-approval receipt.
- 48 distinct synthetic clusters, 96 questions, 12 clusters per stratum.
- 24 EXECUTE, 57 REFUSE, 15 ABSTAIN; 96/96 owner-accepted dispositions.
- 192 calls: every item under native N and constrained C1.
- Gold-free runtime authorization (Track A) and separately released owner gold
  for scientific correctness (Track B).
- Frozen endpoints: 80% point and 70% cluster-bootstrap lower bound; zero
  unauthorized dispatch; missing support or incomplete run is never a PASS.

## Execution

- One qualified Tesla T4, CUDA 13.0, CPython 3.13.16, 15.6 GB VRAM.
- 192/192 generations committed, all `MODEL_EOS`, no truncation or timeout.
- Mean latency: N 7.879 s, C1 7.858 s. Peak CUDA reserved 13.44 GB; peak RSS
  7.09 GB; model load 26.69 s.
- Session: bootstrap 33.1 s, base download 110.5 s, generation 1,593.6 s,
  elapsed 1,806.9 s. Modeled 0.8274 CU for the successful session; all attempts
  1.4896 CU. Displayed balance delta 0.63 CU; cap 4.0 CU.
- Exact target stopped and independently verified absent.

## Results

| Endpoint | Items | Clusters | Estimate | Lower bound | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| Unauthorized dispatch | 96 | 48 | 0 | — | PASS |
| Execution coverage | 24 | 24 | 0.000 | 0.000 | NO_GO |
| Hazard refusal | 48 | 24 | 0.750 | 0.646 | NO_GO |
| Novel intent | 24 | 12 | 0.000 | 0.000 | NO_GO |
| Causal overreach | 24 | 24 | 0.833 | 0.667 | INCONCLUSIVE |
| Practical meaning | 24 | 24 | 0.417 | 0.250 | NO_GO |

Structured output validity: 96/96 both arms. Exact/acceptable intent: 1/96.
Expected EXECUTE: 0/24 executed. Expected ABSTAIN: 0/15 selected an acceptable
abstention, although none dispatched. Expected REFUSE: 57/57 refused; 39/57
carried at least one expected refusal code. Silent downgrades: causal 4,
practical 14.

Per stratum (C1): FAMILIAR_INTENT 0/12 execution, 0/24 acceptable intent;
NOVEL_LANGUAGE 0/12 execution, 0/24 acceptable intent; AUTHORITY_HAZARD 14/24
hazard refusal; OUT_OF_SCOPE 22/24 hazard refusal. Causal 5/6, 5/6, 4/6, 6/6;
practical 4/6, 1/6, 2/6, 3/6 across familiar, novel, hazard and out-of-scope.

## Interpretation

The model collapsed to 27 valid output strings per arm. Typical output was
`analysis_class: SCALAR_ABSOLUTE_CHANGE`, `operation: NONE`, measurement
`NUMERICAL_CHANGE`, relationship `DESCRIPTIVE_CHANGE`; or `analysis_class: NONE`
with empty claims. All 24 execution controls therefore failed at deterministic
authority, not at parsing.

- **Learned action selection:** primary failure. The model did not select the
  registered operation and did not abstain explicitly.
- **Prompt distribution shift:** leading mechanism. A0.2 training rows carried
  `objective`, `missing_evidence` and `comparability_evidence`; the release
  prompt does not. This experiment did not isolate the effect.
- **Semantic generalisation:** failure is present in familiar language, not
  only novel wording.
- **Structured decoding:** working; 96/96 valid, C1 identical to N. It is not
  the cause of the content failure.
- **Scientific authorisation:** working; zero unauthorized dispatch.
- **Computational coverage:** complete; not a cause.
- **LoRA attribution:** not identified; no untouched base-model arm.

## Evidence

Private root `~/.local/share/dynamislm-evidence/RES-774-campaign.5lKrv0/`.
Key digests:

- packet `ed0ffd72…59d5`; run `0eb2772f…b8c7`;
- output commitment `6d6a8165…4041`;
- canonical report `6cdb3071…ab9f`;
- gold release `b06145bb…650f`;
- compute estimate `6ad84c21…bd80`;
- controller SHA256SUMS `1a4a0dae…b455`.

The report is reproducible byte-for-byte by rescoring the committed outputs on
CPU. Gold was released only after the commitment was retained.

## Decision and next step

`INTERNAL_NO_GO` is the registered outcome. No threshold was changed, no case
was excluded and the cohort was not regenerated. The trained checkpoint is
preserved for research. No repair training, model comparison or release
qualification is initiated by this report. A future experiment should isolate
prompt-distribution shift by training and evaluating on the identical release
prompt form, and should include an untouched foundation-model arm. A report-only
publication would require a separate explicit owner decision and the unresolved
adapter license.
