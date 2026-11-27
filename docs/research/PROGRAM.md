# DynamisLM research program

Status as of 27 November 2026. Scheduling authority lives in the Linear project
DynamisLM (team Research). This file records the program and the A0 historical
study in Git. It changes no historical result, threshold, hash or fixture.

DynamisLM develops and empirically studies specialized scientific language
models. Infrastructure is built only when an experiment needs it.

**Research question.** How can compact language models acquire domain-specific
scientific knowledge, develop mathematical and scientific reasoning, interact
with deterministic computational instruments, and generalize to unseen
scientific problems?

**Initial domain.** Football performance science, with transferable
biomechanics, exercise physiology, measurement science, statistics, signal
processing and computational modelling.

The program keeps four things apart:

1. Learned model capability.
2. Deterministic scientific computation (RES-69, RES-70, RES-71).
3. External evidence retrieval.
4. Scientific validity and empirical applicability.

## Tracks

| Track | Status | Linear milestone |
| --- | --- | --- |
| A — DynamisLM-Action: scientific action selection and tool learning | Active | Track A — Scientific Action Selection and Tool Learning |
| B — DynamisLM-Science: knowledge and domain adaptation | Proposed; independent of A | Track B — Scientific Knowledge and Domain Adaptation |
| C — DynamisLM-Reason: mathematical and multistep scientific reasoning | Proposed; independent of A | Track C — Scientific and Mathematical Reasoning |
| D — DynamisLM-Unified: integration | Proposed; integration is a hypothesis | Track D — Unified Scientific Language Model |

The tracks are capability programs. They do not assume separate architectures
or permanently separate checkpoints. Experiments, datasets, checkpoints and
releases are separated by track, and shared code is reused.

## Track A

### Hypotheses

- **H1.** Training–inference representation mismatch contributed to the A0
  failure.
- **H2.** Synthetic generator artifacts encouraged shortcut learning.
- **H3.** Contrastive and compositionally diverse supervision improves
  generalization.
- **H4.** Removing redundant, deterministically derivable output fields
  improves semantic prediction. `operation` is determined by
  `operation_for(analysis_class, len(observation_ids))` in
  `scripts/a02_v3_contract.py`.
- **H5.** Constrained decoding improves structural validity but not
  necessarily semantic correctness.
- **H6.** Scientific domain adaptation (Track B) may help action selection.
  This is optional and not a prerequisite.

### Issues and dependencies

```text
A0 (done) ─► A1 RES-832 ─► A2 RES-833 ─► A3 RES-834 ─► A4 RES-427 ─► A5 RES-835 ─► A6.3 RES-838
                 │              └──────────────────────────────► A6.2 RES-837
                 └─► A6.1 RES-836 manuscript (starts now; later sections follow results)
```

| Step | Issue | Compute | Gate to the next step |
| --- | --- | --- | --- |
| A1 diagnosis | RES-832 | ≈ 5 CU T4 expected, 12 CU cap; inference only | A justified intervention recommendation |
| A2 dataset | RES-833 | CPU | Shortcut audit passes |
| A3 training | RES-834 | ≈ 17 CU per M2 run (provisional) | DEV-OOD acceptable intent ≥ 0.70 (LB ≥ 0.55) and ≥ 0.20 above M0 |
| A4 multi-tool | RES-427 | ≈ 1 training run | Prespecified tool-selection macro-F1 |
| A5 final evaluation | RES-835 | ≈ 3.5 CU | Prospective qualification targets and an adaptation-improvement criterion |
| A6 releases | RES-836, RES-837, RES-838 | None | Explicit owner publication decision |

Each GPU campaign needs one measured envelope and one owner approval. It then
runs autonomously within that envelope. A failed primary training campaign is
reported, not retried indefinitely.

### Superseded or parked issues

- **RES-775** is Canceled. Its entry condition (a failure attributed to adapter
  intent) was not met, and its role moved to A1–A3.
- **RES-777** is Canceled. Its qualified-result precondition failed.
- **RES-746** (independent validation) is preserved. It is not a Track A
  prerequisite.
- **RES-420, RES-421, RES-424, RES-415 and RES-425** keep their formal-program
  scope. Each carries a note that it does not gate Track A.
- **RES-423, RES-426 and RES-429** are parked under Tracks B, C and D.

## A0 — historical study (complete, negative)

### Artifact

| Item | Value | Source |
| --- | --- | --- |
| Base | `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1` | `docs/release/ALPHA-0.1-MODEL-CARD.md` |
| Adapter | Frozen step-510 LoRA: r16, α32, dropout 0.05, q/k/v/o; 7,667,712 trainable parameters | Model card; private adapter metadata |
| Adapter weights | `7bda8c60c2e27206d60a41f7f454ecce721e46704e731b4f6c268d042572a6e7` | Model card |
| Training data | 2,800 synthetic A0.2 TRAIN rows (200 per family × 14), manifest `746cad1b…2569` | `experiments/a02/model-comparison-protocol-v3.json` |
| Supervised target tokens | 385,600 | Private adapter metadata (sha256 below) |
| Objective | Target-only next-token cross-entropy; AdamW, lr 2e-4, 2 epochs, 16,384-token batches, seed 541 | `scripts/a02_v3_training.py`; protocol v3 |
| Precision | FP16 base, FP32 adapters, gradient checkpointing, deterministic algorithms | `scripts/a02_v3_training.py` |
| Training run | 510 optimizer steps on one T4; median 34.4 s per step in the final session; loss per target token fell from a median 0.131 (first 20 steps) to 0.00064 (last 20) | Private session report and audit |

### A0.2 development result (held-out, generator-produced)

280 held-out rows: 20 per family, 15 template clusters, about 8.12 effective
clusters. Exact full-action match:

| Arm | Exact | Notes |
| --- | ---: | --- |
| Adapted, native | 255/280 | CAUSAL_OVERREACH 7/20, PRACTICAL_MEANING 9/20, QUESTION_ADDS_CAUSAL 19/20, all other families 20/20 |
| Adapted, C0 option-ranking constrained | 50/280 | 205 items were correct native but wrong constrained |
| Zero-shot base, native | 0/280 | 0 valid outputs (truncation and invalid claim axes) |
| Zero-shot base, C0 constrained | 0/280 | 280 valid outputs, none exact |

- The preregistered `adapted_exact_floor` check failed.
- The decision was `ESCALATE_TO_STRONGER_MODEL_COMPARISON`.
- On the 10 exposed development cases, adapted native was 8/10 and adapted
  constrained 1/10.
- Source: private audit
  `/mnt/e/DynamisLM-A0/a02/v3-lora-stage2-v1/RES541-results-audit/audit-findings.json`,
  sha256 `5d519637a1f3a6d52eef97c24995f69e2f53dfc8b258903faee63c18638d1821`.
- Private adapter metadata: `.../final-single-t4-continuation-008-v1/final-adapter/metadata.json`,
  sha256 `1f3bcf6abe549d855ad89d32d54b9040af4be66ee81f3115f9c308852d1d11a4`
  (the training-metadata digest in the model card).

The A0.2 C0 decoder ranks options by sequence log-probability. It is not the
RES-774 C1 token mask.

### A0.3 operational evaluation (RES-774)

The cohort has 48 owner-adjudicated synthetic clusters and 96 questions:
24 EXECUTE, 57 REFUSE and 15 ABSTAIN. Both decoding arms ran on one T4 in FP32
with greedy decoding.

| Measure | Result |
| --- | --- |
| Generations | 192/192 completed, all `MODEL_EOS` |
| Structured-output validity | 96/96 in both arms |
| Exact or acceptable intent | 1/96 |
| Execution coverage | 0/24 |
| Novel-language intent | 0/24 |
| Hazard refusal | 0.750 (LB 0.646) |
| Causal | 0.833 (inconclusive) |
| Practical meaning | 0.417 |
| Unauthorized dispatch | 0 |
| N vs C1 | Token-identical on all 96 items |
| Latency | Mean 7.879 s (N) and 7.858 s (C1) per call |
| Session | 1,806.9 s; 0.8274 CU modelled |
| Verdict | `INTERNAL_NO_GO` |
| Publication | `NO_GO` (`docs/release/ALPHA-0.1-RELEASE-DECISION.json`) |

### Representation difference (descriptive)

**Training request** (`scripts/a02_v3_synthetic.py`) carries:

- `objective`, a template text;
- `question`;
- a free-text `measurement`;
- observations with role, time and processing method;
- constant `available_evidence`, `missing_evidence`, `football_context` and
  `source_documentation` strings;
- `comparability_evidence`.

**Release request** (`BoundRequest.model_request()` in
`scripts/a03_scientific_admission.py`) carries:

- `question`;
- observations with registry stable ids for measurement, protocol and device;
- `requested_claims`.

**Shared system prompt.** Both use
`experiments/a02/system-action-development-v3.txt`, which refers to an
`objective` field that the release request does not contain.

**Generator artifacts.** Training gold selects every observation whose
measurement matches the label. Cardinality is 1–3. The intent templates repeat.

### Interpretation boundary

The difference between A0.2 and A0.3 is descriptive. The evaluation
distributions, input representations and scoring conditions all differ, so no
isolated causal effect is claimed.

- The untouched base was never run on the RES-774 cohort.
- LoRA attribution is not identified.
- The checkpoint is historical evidence, not a qualified release.
- The formal PSE V1 `SCIENTIFIC_NO_GO` and the RES-746 program remain
  separate historical decisions.

## Release requirements

1. **A6.1 manuscript (RES-836).** Working title: *When Valid Tool Calls Are
   Scientifically Wrong*. Section 4 (A0) can be drafted now. Later sections
   must separate proposed experiments from completed results. The manuscript is
   valid even if model recovery fails.
2. **A6.2 dataset (RES-837).** `DynamisLM-Action-SFT-v1`. Contents: eligible
   synthetic splits, generation code, data card, split manifests, license and
   byte-identical regeneration. Requires an owner license decision and
   publication decision.
3. **A6.3 model (RES-838).** Proposed name `DynamisLM-Action-3B-v0.2`, used
   only if the 3B architecture is kept. Requires a QUALIFIED A5 result.
   Contents: adapter, base revision, training configuration, model card,
   four-layer evaluation, limitations, inference examples, tool definitions,
   source, `SHA256SUMS` and licensing. Base weights are not redistributed.

Code and reproducibility are published on GitHub. Eligible weights and data
are published on Hugging Face. A negative-result report is not a model
release.
