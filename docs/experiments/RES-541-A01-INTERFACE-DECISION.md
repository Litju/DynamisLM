# RES-541 — A0 NO_GO: model-interface diagnosis and A0.1 decision

**Decision state:** RESEARCH REVIEWED / A0 SCIENTIFIC **NO_GO** / A0.1 **NOT RUN**  
**Scope:** RES-541, existing draft PR #46, development-only synthetic cases.  
**Source baseline:** `a7216366e46c3a80bd20435a6d894e917d90e5f0`; existing A0 v1 remains immutable.  
**Compute:** None authorized by this decision. No model retraining or further GPU run was performed for this review.

## Provenance and evidence boundary

The experiment operator reported a SHA-256-verified, CPU-replayed forensic postmortem on E: at:

- Raw report: `/mnt/e/DynamisLM-A0/reports/res541-a0-20261023-040456z-report.json`
- Raw report SHA-256 **operator-reported**: `d0881e600cc7b729c894122db504f596dab60a270814ff47796a662e87482303`
- Review: `/mnt/e/DynamisLM-A0/reviews/res541-a0-20261023-040456z-postmortem-v1/scientific-review.md`
- 16-case analysis: `.../per-case-failure-analysis.json`
- Proposed A0.1 prompt: `.../a0.1-system-prompt-v1.txt`

These E:-local postmortem bytes are **not** part of this GitHub PR and were **not independently fetched into this review context**. The counts below are explicitly *operator-reported, CPU-replayed* findings, not reconstructed here from private local raw outputs. The repository source and parser behavior were inspected independently.

| A0 outcome | Operator-reported count |
|---|---:|
| Syntactically valid JSON | 16/16 |
| Strict typed-intent valid | 1/16 |
| Intent matched expected | 0/16 |
| Parser fallback refusals | 15/16 |
| Model explicit refusal | 1/16 |
| Registered scientific dispatch | 0/16 |
| Correct numerical outcomes | 0/7 |
| Expected canonical refusal reasons | 0/9 |
| Generation hitting 64-token cap | 0/16 |

The evidence does **not** validate SmolLM3's scientific reasoning quality or falsify the deterministic scientific engine. It establishes failure of this specific, zero-shot model-to-intent interface. All-safely-refused is not useful computation; no generated numeric value means the `0 invented numeric values` count is vacuous, not a proven reliability rate.

## Source-backed root-cause analysis

1. **Invalid demonstrations in the system prompt — strong hypothesis.** `scripts/a0_colab_inference.py` gives JSON-shaped example fields whose *literal string values* are descriptions (`"AnalysisClass enum value"`, `"BASELINE|FOLLOWUP|null"`, a pipe-delimited refusal-reason menu). `scripts/a0_engine.py::parse_model_intent` correctly rejects these as enums/nullable fields. Operator-reported outputs directly imitated the strings and mixed field domains. This is a plausible prompt-induced failure; **without a controlled revised-prompt run it is not established as the entire causal explanation**.
2. **Routing-versus-authorization ambiguity — architectural interface defect.** A0 uses `EXECUTE` to mean *submit requested analysis to deterministic authorization*, not *perform an already authorized computation*. A missing baseline is still a representable `SCALAR_ABSOLUTE_CHANGE` request; the canonical Python authority must decide whether support is sufficient. A high-level model `REFUSE/MISSING_EVIDENCE` instead short-circuits the canonical error code. The final refusal can be semantically understandable but invalid for this experiment's routing objective.
3. **Model capacity / context / decoding limitations — unresolved alternatives.** SmolLM3-3B may fail to reliably fill role and claim-axis fields even under valid examples; the current run does not isolate this. No case reached 64 generated tokens, so truncation is **not supported as the explanation of A0**. The official SmolLM3 chat template supports `enable_thinking=False`, already set. Prompt examples may nevertheless push **new A0.1** inputs over the existing 1,024-token prompt cap: test exact tokenized prompts on CPU first.
4. **Scoring responsibilities need interpretation discipline.** A malformed model response is a *parser safety fallback*, not a correct model-side scientific refusal. The canonical `RES69_`/`RES70_` refusal is a *Python authority decision*, not an LLM refusal label. Report these separately. Refusal precision is undefined whenever TP+FP = 0; do not substitute 0% or 100%.

## Architecture decision: preserve the division of authority

Keep the following invariant:

```text
question + bounded evidence
        |
        v
LLM: infer requested scientific action and claim intent
        | typed, untrusted proposal (never Python code or computed truth)
        v
strict schema + enum + identity resolution
        |
        v
registered RES-70 authorization --> canonical refusal (if ineligible)
        |
        v
registered RES-69 numerical operation --> validation
        |
        v
RES-70 claim authorization --> bounded deterministic rendering
```

Scientific permission, formula choice, numerical validity, comparability, and evidence-dependent refusal reasons remain **deterministic**. The language model must not substitute its own approval or reason codes for the engine's decision. The current strict rejection boundary is correct and must not be weakened by regex repairs, auto-inferred missing fields, permissive defaults, or model-authored numbers.

### A0.1 — first falsifiable experiment (prompt-only, unchanged V1 wire protocol)

- Keep the **same pinned SmolLM3 checkpoint**, synthetic dev-only case identities, strict `RES541_A0_INTENT_V1` parser, registered engine, FP16/greedy decoding and run bounds. Version the prompt separately (`A0.1_PROMPT_V1`) and preserve the original prompt/result digest intact. Never relabel the old NO_GO.
- Replace JSON-shaped **placeholder** values with short, **actually valid concrete JSON outputs**. Explicitly distinguish native `null` from quoted `"null"`; specify exact allowed `AnalysisClass`, role, measurement, and relationship enum sets; distinguish EXECUTE fields from REFUSE fields (no `x` on execute).
- State unambiguously: **`EXECUTE` in V1 means “SUBMIT_FOR_AUTHORIZATION,” not “authorized/execute now.”** For *representable* missing-evidence, comparative, relative-change, causal or unsupported statistical requests, emit the proposed analysis/claim intent and let Python refuse if appropriate. Reserve V1 model `REFUSE` only for inputs that genuinely cannot be mapped into the available intent taxonomy.
- Use a small number of genuinely valid demonstrations, including both a valid numeric proposal and a representable-but-scientifically-ineligible proposal. Review the operator's separate eight-example E: candidate; **do not silently assume it fits** `MAX_PROMPT_TOKENS=1024`. Prune examples rather than expanding compute limits merely to fit a prompt.
- CPU tests must parse every prompt demonstration, verify exact native types/field sets and role semantics, render the **pinned official model's** chat template, assert all full prompt token counts (system + actual user evidence + template metadata) are within the unchanged 1,024-token bound, and verify intended compact outputs fit the 64-token generation ceiling. A unit test that only asserts a mock tokenizer string is insufficient to prove actual tokenizer fit.
- **Before any new GPU use**, preserve SHA-256 for the new prompt, 16-case manifest, exact model revision, tokenizer configuration, dependency versions, source code and decoding policy. SmolLM3's template may inject the current date; preserve each actual tokenized-prompt hash and run date in the receipt.
- The already examined 16 cases are **development cases**, exposed during prompt diagnosis. Report an A0.1 replay on them as a *diagnostic comparison*, never as an untouched generalization test. Precommit separate independently written, truly new synthetic development controls before seeing their outputs; do not inspect the protected PSE benchmark.
- No GPU run is authorized merely by completing CPU setup. Require fresh owner consent to exact Colab cost, source/prompt SHA, GPU tier and bounded case count; maintain E: host storage and remote-ephemeral weights.

### If A0.1 output format improves but routing remains wrong: deliberate interface V2

**Do not change V1 during A0.1.** After its results, consider a separate versioned V2 with an explicit intent-stage action such as `SUBMIT_FOR_AUTHORIZATION` versus `UNMAPPABLE_REQUEST`. The model should identify *what the user requested*, not decide whether sufficient evidence exists to compute it. The canonical authority alone returns scientific refusal classes/reasons. Compare V1 vs V2 on precommitted cases; update parser and scoring with adversarial tests only after a documented design decision.

### If A0.1 remains syntactically invalid: optional output constraints

SmolLM3's **pinned model card** documents native `xml_tools` tool-call formatting as an alternative to our bespoke JSON response. Test its exact pinned chat-template rendering and parser compatibility offline before a GPU comparison. XGrammar provides Hugging Face Transformers logits processors for JSON-schema-constrained decoding as a separate experiment. Constrained decoding can enforce syntax/schema **but cannot guarantee correct scientific intent**, so semantic routing metrics and strict Python authority remain required. Avoid introducing a new serving framework, dependency stack, or training before evidence justifies it.

### Only then consider changing model / SFT / CPT

Do not infer that a larger model or continued domain pretraining is needed from copied placeholder strings. A controlled A0.1 trial with valid examples and explicit routing semantics is the cheapest discriminator. If valid structured outputs remain semantically wrong, test a **separate pinned inference candidate** only with fair identical frozen developer cases and compute permission; use model finetuning later only with licensed training data and distinct evaluation data. Formal M0/PSE gates are unchanged.

## Minimal scoring contract for the next diagnostic receipt

Report integers/denominators and raw case decisions separately:

- JSON syntax validity and **strict typed-schema validity**.
- Analysis/claim-axis/role **semantic intent exact match**, regardless of eventual refusal.
- Explicit model `REFUSE` count, classification, and whether the input is actually unmappable.
- Parser-fallback count, including invalid enum, wrong field set, quoted null, imitation and truncation (overlaps identified).
- Deterministic RES-70 analysis authorization accepts/refusals and their **canonical** reasons; registered RES-69 calculations and result hashes.
- Claim-authorization accepts/refusals; no unauthorized computations; raw numeric integrity only **when outputs exist**.
- Prompt length, generated-token length, latencies, VRAM and session teardown.

**A0.1 research milestone:** at least one genuine LLM-originated, strictly typed `SCALAR_ABSOLUTE_CHANGE` submission reaches the **registered** numeric result path with correct units/provenance, and at least one representable but invalid scientific request reaches **canonical** authority refusal, with zero unauthorized numerical outputs. These are minimum *development integration smoke criteria*, **not** scientific accuracy or generalization qualification. Also report all 16 cases transparently, even if this minimum is met.

## Primary external references

- Exact [SmolLM3-3B pinned model card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/blob/a07cc9a04f16550a088caea529712d1d335b0ac1/README.md) — non-thinking mode, `xml_tools` tool calling, known model limitations.
- [Transformers v4.53.0 SmolLM3 documentation](https://huggingface.co/docs/transformers/v4.53.0/en/model_doc/smollm3) — pinned inference stack compatibility.
- [XGrammar Hugging Face JSON-schema logits processor](https://xgrammar.mlc.ai/docs/latest/start/quick_start.html) — alternative constrained-output mechanism, subject to compatibility verification.
- [JSONSchemaBench](https://arxiv.org/abs/2501.10868) — distinguishes constraint coverage, output validity and output quality.
- [Berkeley Function Calling Leaderboard (ICML 2025)](https://proceedings.mlr.press/v267/patil25a.html) — distinguishes function/tool-call selection and abstention.

**Disposition:** A0 NO_GO preserved. A0.1 design candidate permitted for **CPU-only** implementation/review in **this same RES-541 issue and PR #46**. No GPU, training, merge, or release authorization.
