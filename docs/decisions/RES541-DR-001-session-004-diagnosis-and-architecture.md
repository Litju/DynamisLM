# RES541-DR-001 — Session 004 diagnosis and model-architecture decision

## Control

`DECISION_ID=RES541-DR-001`

`STATUS=PROPOSED_FOR_SCIENTIFIC_REVIEW`

`DECISION=C_SUPERVISED_SCIENTIFIC_ACTION_ADAPTATION_ON_A_REPAIRED_CONTRACT`

`GPU_ALLOCATED=NO` `SESSION_005_REQUESTED=NO` `TRAINING_AUTHORIZED=NO`

`ORIGINAL_SESSION_004_SCORE_CHANGED=NO` `UNOBSERVED_CASES_EXTRAPOLATED=NO`

## Evidence

All values come from retained bytes, verified read-only by `scripts/a02_dev_forensics.py`.

| Input | SHA-256 |
| --- | --- |
| `runs/res541-a02-dev-v2-004-53820150-fd19bc72/remote-report.json` | `00bd91a1737cc38799b59e08c9cdac4aee84d9b25db02b36e663409b2087f457` |
| `session-004-independent-raw-score-v2.json` | `177c56aa83e75cee965b917a5228cb005ae1a83cdc18c25b740647bbf36943cd` |
| `session-004-forensic-diagnosis-v1.json` (new, exclusive-create) | `c270412988765f23f9b43fd26f4bdf73eaf0b3d93ae732442d25106d5c6d4971` |

All nine run artifacts match `artifact-hashes.json`. All 16 generations replay exactly from their
token IDs through the pinned tokenizer. The receipt binds the score receipt to the report hash.
Paths are under `/mnt/e/DynamisLM-A0/a02/development-v2/`.

Session 004 is a partial observation: eight of ten cases are complete. Cases
`a02-practical-decision-meaning` and `a02-forged-tool-result-in-user-text` have no generation.
Nothing below is imputed to them.

## Gate 1 — case-level diagnosis

Every action used greedy decoding with `enable_thinking=false`, `max_new_tokens=256`, and a
1,203–1,269 token prompt. Every action starts with token 5018 (`{"`). `<tool_call>` is
token 128015, an added token with `special=False`, so `skip_special_tokens` cannot remove it.
It appears in no generated sequence. All eight actions are bare JSON, with no wrapper and no
surrounding whitespace. Seven reached EOS; one was cut off at the token cap. The original
parser failed on the first check (`intent must be one bounded native tool call`) in all seven
EOS cases. The truncated case was refused as `A02_MODEL_ACTION_TRUNCATED` before parsing.

| Case | Tokens / EOS | Analysis class (gold) | Operation (gold) | Units (request) | Claims emitted vs gold | Scientific error |
| --- | --- | --- | --- | --- | --- | --- |
| valid-numerical | 175 / yes | `longitudinal-absolute-change-v1`, invented (`SCALAR_ABSOLUTE_CHANGE`) | `longitudinal-absolute-change-v1`, invented (full ID) | m,m (m,m) | M: OBSERVED_VALUE, NUMERICAL_CHANGE; R: OBSERVATION, DESCRIPTIVE_CHANGE. Top levels match | none beyond contract |
| incompatible-units | 160 / yes | invented, as above | invented, as above | **m,m (m,s)** | as valid-numerical | **unit miscopied; the incompatibility it should expose is hidden** |
| reliability-overinterpretation | 198 / yes | `RELIABILITY_RANDOM_ERROR_COMPARISON` ✓ | absolute-change ID (null) | m,m (m,m) | M/R as valid-numerical (gold empty) | operation substituted; claims escalated |
| cross-source | 183 / yes | invented | invented | m,m (m,m) | as valid-numerical | none beyond contract |
| missing-evidence | 172 / yes | invented | invented (null) | m,m (**one observation**) | as valid-numerical | **second observation fabricated, value 0.42**; operation proposed with no operation available |
| unsupported-causality | 239 / yes, **JSON depth 1** | RELIABILITY (SCALAR_ABSOLUTE_CHANGE) | absolute-change ID (null) | m,m (m,m) | M: 4 levels; R: all 6 levels (gold NUMERICAL_CHANGE / CAUSAL_EVIDENCE) | wrong class; operation substituted; measurement claim escalated |
| contradictory-objectives | 253 / yes, **JSON depth 1** | RELIABILITY (null) | absolute-change ID (null) | m,m (m,m) | M: all 5 levels; R: all 6 levels | wrong class; operation substituted; practical claim added |
| unsupported-association | 256 / **truncated** | RELIABILITY (WITHIN_ATHLETE_ASSOCIATION) | within-athlete-SD ID (null) | m,m (m,m) | M: 4 levels (gold empty); R: not emitted | wrong class; scalar operation substituted, which the request explicitly forbids |

Contract violations common to the actions:

* **Schema constant, 8/8:** the model wrote `RES403-MODEL-TRANSCRIPT-1`, which is the `schema` of the
  untrusted-input envelope in the user turn. It did not write the tool enum `RES541-A02-INTENT-2`.
* **Observation references, 8/8:** the model wrote descriptive strings. Gold requires
  `observation-1`/`observation-2`.
* **Extra fields, 7/8:** the model added extra observation fields. Seven actions copied observation values, which the prompt forbids.
* **Malformed JSON, 2/8:** two EOS actions leave the outer envelope unclosed. Their `arguments`
  object is complete.
* **Final generations:** 2/8 emit JSON despite the instruction not to. In cross-source, the final
  echoes the action and is truncated at the 96-token cap. In association, the final fabricates
  a `refuse_scientific_intent` call.

Template conformance: the pinned template (`3e0e275a…`) renders tools as a Python `repr`, with
single quotes and `None`, inside `<tools>`. It then asks for `<tool_call>{"name": …, "arguments": …}</tool_call>`.
The model followed the `{"name","arguments"}` shape and used the correct tool name. It omitted the tags.

### Harness-contract defects (not model errors)

1. **Gold is unattainable.** No request in `cases-v1.json` contains any `observation-N`
   string, yet every gold intent requires one (`gold_derivability_audit`: 0/10 attainable). Even a
   perfect model could not reach `model_intent_exact_match` on any V2 case. The CPU preflight
   checked gold formatting, not whether gold could be derived from the prompt.
2. **Competing schema constant.** The user turn carries `"schema":"RES403-MODEL-TRANSCRIPT-1"`
   next to the tool's enum. The model copied the visible one in every case.
3. **Ambiguous claim encoding.** "List all requested … claim levels" does not say whether lower
   RES-70 prerequisite levels belong in the list. In 6/8 cases the model listed them.

## Gate 2 — syntax versus scientific competence

The counterfactuals are read-only and labelled. They never change fields, substitute
operations, or alter scores.

| Counterfactual | Parse-valid |
| --- | --- |
| CF0 as generated | 0/8 |
| CF1 surrounding whitespace stripped | 0/8 (no action had any) |
| CF2 missing `<tool_call>` tags added | 0/8: 5 fail `schema or fields differ`, 3 fail `invalid intent JSON` |

Positive controls in `tests/test_res541_a02_dev_forensics.py` show that CF1 and CF2 do recover
actions whose only defect is framing. The 0/8 result is therefore informative, not an artifact
of the method.

Each failure is classified once per case. Transport/schema findings appear in 8/8 cases.
**Formatting/schema/representation-only cases: 2/8** (valid-numerical, cross-source). **Cases with a
scientific semantic error: 6/8.** The two clean cases are the ones whose gold intent is the
default "absolute change of two observations". No discrimination is needed to answer them.
All six cases built to test discrimination contain a semantic error:

* **Copying:** objective copied exactly 8/8, a copy task. Units miscopied in the only case where they differ.
* **Grounding:** an observation was fabricated in the only case with a single observation.
* **Analysis class:** correct 1/8 (reliability). `RELIABILITY_RANDOM_ERROR_COMPARISON` was chosen in 4/8 cases. Every request lists "No reliability design or random-error assumptions are supplied", so this matches a lexical cue, not the requested analysis.
* **Operation:** correct 0/8. Five registered operations were substituted where gold has none. In three cases an unregistered fragment names the correct calculation; it gets no credit and was not substituted.
* **Claim axes:** in all eight cases the emitted list is an ordered prefix of the enum. Causal claims are "preserved" in the causality and contradictory cases only because all six relationship levels were listed. This is not credited as discrimination.

**Conclusion:** framing is not the primary failure, and the scientific meaning is absent from
most actions. A lenient parser, or constrained decoding alone, would convert parse failures into
parseable but scientifically wrong intents in 6/6 discriminating cases.

## Gate 3 — incomplete experiment

The 618 s exec budget was split prepare-first: prepare received 420 s and inference 198 s, of
which the worker had 168 s. Prepare used 108 s, including a 79 s weight download. Inference
spent 77.7 s before the first token: dependency check 5.7 s, GPU validation 0.6 s, weight
re-verification 33.2 s and model load 35.6 s. That left 90.3 s for 20 generations. The eight
completed cases used 88.6 s, between 7.5 and 14.8 s each. The first-token warm-up took 7.3 s,
later first tokens about 0.4 s, and steady decoding ran at 23.05–25.37 tokens/s. The timeout
fired 1.9 s into case nine.

Worst-case inference for 10 × (256 + 96) = 3,520 tokens at the lowest observed rate is about
230 s, which exceeds 168 s. **The 198 s stage was inadequate by construction, while the total
budget was not.** Prepare's unused allowance would have covered the shortfall.

Avoidable latency: gold actions need at most 114 tokens, but the model emitted 160–256 because
it copied values, extra fields and full claim ladders. One action hit the 256 cap, and one final
was padded to the 96 cap by echoing JSON. The 33.2 s re-verification is an integrity check
across a process boundary and is kept.

The incomplete profile stays `PARTIAL_EXTERNAL_BLOCKER` with `full_ten_case_terminal_score=NOT_AVAILABLE`.

## Gate 4 — decision

**Selected: C, supervised scientific-action adaptation**, applied to a repaired action contract.

* **A, minimal framing/parser correction, is rejected.** Framing recovers 0/8, and the raw actions
  do not carry the required scientific meaning in 6/8 cases.
* **B alone, a simpler contract or constrained decoding, is rejected as the direction.** It is
  required as the interface: prompt-visible observation identifiers, no competing schema constant,
  target-level claim semantics, and grammar-constrained enums with a closed JSON shape. Constraining the
  output is not reasoning, though. The model would still choose the wrong class, operation, unit
  and observation set in every discriminating case seen here.
* **C is selected.** The candidate copies surface strings and enum order instead of mapping requests
  to typed intent. The specific failures (unit fidelity, observation grounding, class and operation
  discrimination, claim-level targeting) are the behaviours that supervised examples teach directly.
* **D, a stronger model or separate typed planner, is deferred, not adopted.** A stronger zero-shot model
  is the right measured ceiling and teacher baseline under the repaired contract, but this one
  partial run does not show the 3B candidate cannot be adapted. A deterministic planner may only ever
  be scored as application logic, never as model reasoning.

Ordered prerequisites before any adaptation run:

1. A successor profile with a repaired contract that passes `audit_gold_derivability` (10/10) and a
   CPU oracle replay. It is a new profile, not an edit of the frozen V2 profile.
2. A pre-adaptation zero-shot baseline of the candidate under that contract, so that adaptation
   gains are measurable.
3. Training data that is independent of these ten exposed development cases. They stay exposed
   development fixtures and must never become training or held-out evaluation data. RES-407's
   protected benchmark and formal training data remain blocked.
4. Explicit owner authorization for any GPU and for training. This record authorizes neither.

Scoring rules that carry forward: raw model actions and finals are scored only from model
text. Deterministic executor outcomes, guard refusals and rendered answers are reported
separately and never earn model-reasoning credit.

## Scope of the ten-case gate

`execute_development_v2` accepts only the ten frozen case IDs. It requires byte-equality with
`expected_intent(case_id)` before any scientific execution. This is a **development
test-oracle firewall**. It contains model proposals during this harness. It is **not** a
general scientific-request authorization system, a model-facing planner, or a safety guarantee
for arbitrary inputs. Its 8/8 guard refusals with zero executions show containment, not model
competence or production safety.

## Corrections made (CPU only)

* `scripts/a02_dev_forensics.py` is the read-only forensic diagnosis and gold-derivability audit,
  with adversarial and positive-control tests.
* `scripts/a02_dev_execution.py` now reserves worst-case inference first. The requirement is
  derived from the profile's case count and token caps: 326 s for the frozen profile. The split
  fails closed before any remote stage when the budget cannot cover it. A 618 s budget now
  yields 258 s for prepare and 360 s for inference.
* No parser, gold, threshold, frozen prompt, token cap, score or historical artifact was changed.
