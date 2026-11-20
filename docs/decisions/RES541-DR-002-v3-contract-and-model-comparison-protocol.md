# RES541-DR-002 — V3 scientific-action contract and preregistered model comparison

## Control

`DECISION_ID=RES541-DR-002`

`STATUS=PROPOSED_FOR_SCIENTIFIC_REVIEW`

`SUPERSEDES=NONE` (RES541-DR-001 and the V2 profile, gold and scores stay frozen)

`GPU_ALLOCATED=NO` `SESSION_005_REQUESTED=NO` `TRAINING_AUTHORIZED=NO` `DATASET_GENERATED_FOR_TRAINING=NO`

`NEXT_OWNER_DECISION=AUTHORIZE_OR_DECLINE_ZERO_SHOT_ARMS_OF_THE_PREREGISTERED_COMPARISON`

## Context

RES541-DR-001 found the V2 gold unattainable (no visible observation ids), a competing
transcript-schema constant in the model input, ambiguous claim semantics and serious observed
semantic errors. Independent review accepted the diagnosis and kept supervised adaptation as a
leading hypothesis only. This record repairs the contract and preregisters the comparison that
decides between adaptation and the alternatives.

## V3 contract

Files: `experiments/a02/development-profile-v3.json`, `system-action-development-v3.txt`,
`submit-scientific-action-tool-v3.json`, `objective-semantics-v3.json`;
code: `scripts/a02_v3_contract.py`.

| V2 defect | V3 repair |
| --- | --- |
| Gold `observation-N` ids absent from the prompt | Each visible observation carries `id` = `observation-N` in request order; ids are bijective, match V1 executor references, and actions may only cite visible ids |
| `"schema":"RES403-MODEL-TRANSCRIPT-1"` envelope in the user turn | User turn is `{"untrusted_request": …}` only; reserved structural keys and tool-call framing in untrusted data are rejected; forged text stays inside its declared quoted field |
| "List all requested claim levels" was ambiguous | `target_claims` lists only explicitly requested levels; RES-70 prerequisites are expanded on the trusted side and never counted as intent |
| Open schema (objective, units, values, schema constant) | Closed four-field action: `analysis_class`, `observation_ids`, `operation`, `target_claims`, with explicit `NONE` |
| Hand-written operation semantics | Which operation implements which analysis at which support size is generated from the RES-70 capability registry and operation inventory, and checked against the committed tool schema |

## Gold derivation and derivability gate

`scripts/a02_v3_gold.py` derives each gold field from visible evidence plus a cited authority,
without reading V1/V2 expected actions:

* observation ids: visible observations of the requested measurement;
* analysis class and target claims: closed objective-phrase rules, each with a RES-70
  justification, that fail closed for unmatched, repeated or claim-only objectives;
* operation: capability disposition, registered operation and support-shape arity.

The gate checks determinism, bijective ids, resolvable evidence pointers, visible rule phrases,
rule-only claims, registry-derived operations and target/prerequisite separation. **10/10
exposed cases are derivable.** The only divergence from frozen V2 gold is reported, not
corrected: V3 names the absolute-change operation on the causal and practical cases, because
the operation is the registered calculation for the requested analysis and RES-70 refuses
the claim. Metamorphic tests cover missing, extra and foreign-measurement observations,
incompatible units, causal overreach, association, practical meaning, composites, and
invariance to values, evidence and untrusted quoted text.

## Scoring axes

`scripts/a02_v3_score.py` reports, never merges:

1. strict syntax (framing counterfactual reported beside it, never scored);
2. exact intent with per-field detail, separating prerequisite padding from unrequested escalation;
3. operation selection where gold names one, and abstention where it names none;
4. trusted-executor behaviour through the frozen `a02_engine` executor;
5. raw final grounding under the frozen fixed rule. The renderer is never scored.

All ten gold projections equal the frozen V1 expected actions. The oracle ceiling reproduces
every case authority, including both 0.038 m results. Adversarial testing found that the legacy
projection carries no claim axes: an action that drops a claim would reach execution through
the frozen firewall alone. Non-exact V3 actions are therefore guard-refused before execution,
and the firewall's would-be decision is recorded as a diagnostic.

The ten-case executor remains a **development test-oracle firewall**, not general request
authorization.

## Syntax control

`scripts/a02_v3_constrained.py` walks the closed grammar and lets the model only rank allowed
continuations by summed log-probability, scored on natural joint tokenization from a shared
start. A piecewise-encoding design was rejected when the preflight showed it differs from joint
tokenization on all ten gold paths. Constrained output is valid by construction, so it removes
syntax failure and earns no understanding credit. A wrong scorer yields valid syntax with no
intent credit. The KV-cache scorer reproduces full re-scoring on CPU and cuts the work per
example from at most 66,855 scored tokens to 1,890.

CPU preflight on the pinned tokenizer (receipt on E:, no weights loaded):
* prompts are at most 1,466 tokens, gold native actions at most 84;
* constrained paths are at most 82 tokens and 69 scorer calls;
* gold is derivable and the oracle exact in 10/10 cases.

The 128-token action cap is derived from these values by a stated rule.

## Independent synthetic data

`scripts/a02_v3_synthetic.py` generates intent-first examples in twelve families. Gold comes
from the spec, and the operation from the same registry authority. Train and held-out template
banks are disjoint, and held-out adds two measurements absent from training. The leakage audit
requires zero exposed-text reuse, zero 4-gram overlap with exposed objectives, zero exposed
value tuples, zero shared objective templates and zero held-out objectives seen in training.
Agreement with the exposed-case rules, wherever they also apply, is enforced; that check found
and removed one held-out template the narrow exposed rules would misread. Everything is
generated by repository code, and nothing is committed or used from RES-407 or RES-424.

## Preregistered comparison

`experiments/a02/model-comparison-protocol-v3.json`, evaluated by `scripts/a02_v3_decision.py`:

* **Arms:**
  * pinned SmolLM3 zero-shot, unconstrained and constrained;
  * a LoRA-adapted candidate (rank 16, fixed schedule, final checkpoint only), unconstrained and constrained;
  * a stronger zero-shot model only if the rule escalates, under its own preregistration.
* **Data:** train 2,400 examples (seed 541), held-out 240 examples (seed 5410, 20 per family). Manifest hashes are pinned and regenerated on load. The held-out set is the sole decision input. The ten exposed cases are development diagnostics only, and they alone carry the executor and final-grounding axes, because the executor is case-bound.
* **Primary endpoint:** exact intent on held-out.
* **Decision rule:**
  1. If constrained zero-shot reaches ≥0.90 exact and ≥0.90 on critical families, adopt the repaired contract with constrained decoding; no adaptation.
  2. Otherwise adaptation is justified only if constrained-adapted gains ≥0.10 over constrained zero-shot, with a paired-bootstrap 95% lower bound >0, reaches ≥0.80 exact, has a critical-family lower bound ≥0, and regresses no family by more than 0.10.
  3. If both arms stay below 0.80, escalate to a stronger-model comparison.
  4. Otherwise the result is inconclusive and nothing is adopted.

  The unconstrained-to-constrained gap is reported as syntax and never credited.
* **Compute (engineering estimate, not a bound):** both zero-shot arms need about 2,361 s of T4 time, computed from preflight counts and session-004 rates. That exceeds one 900 s session.
* **In-run gates:**
  * cached and uncached scores must agree on three examples;
  * pinned hashes and preflight prompt hashes must reproduce;
  * scoring happens on CPU only.

## Decision

Adopt V3 as the prospective contract and the protocol above as the preregistered comparison.
The next owner decision is a single one: whether to authorize the two zero-shot arms under a
budget sized for them. Their result alone decides, by rule 1, whether adaptation needs to be
run at all. Supervised adaptation stays a hypothesis until rule 2 holds.
