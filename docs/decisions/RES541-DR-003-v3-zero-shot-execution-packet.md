# RES541-DR-003 — V3 zero-shot execution packet

## Control

`DECISION_ID=RES541-DR-003`

`STATUS=READY_FOR_OWNER_DECISION`

`GPU_ALLOCATED=NO` `SESSION_005_REQUESTED=NO` `TRAINING=NO` `V2_LEDGER_CHANGED=NO` `CAMPAIGN_ALLOWANCE_EXISTS=NO`

`DECISION_REQUESTED=AUTHORIZE_OR_DECLINE_ONE_FINITE_CAMPAIGN_ALLOWANCE_FOR_THE_V3_ZERO_SHOT_RUN`

This packet answers independent review #5824688227 and the RES-541 continuation gates.
RES541-DR-002 remains the record of the V3 contract. Its 2,361 s estimate is superseded; the
engineering estimate is 2,735.7 s and admission uses the worst-case plan below. No V3 model
observation exists. Every figure here was produced on CPU. The Colab GPU path is unverified.

## What the continuation found and fixed

These are defects in the earlier local work, found by trying to falsify it:

| Finding | Fix | Evidence |
| --- | --- | --- |
| **Generated gold had no independent derivation.** The existing "agrees or fails closed" test passed vacuously: all 3,080 generated examples failed closed, so the generator was its own oracle. | A pinned closed-vocabulary adjudication of the complete generator phrasing, written from template text and not from family labels. All 2,800 training and 280 held-out gold actions now agree with it. `load_protocol` refuses any generator whose gold differs, even if the manifest hash is defeated, and names the failing example instead of skipping it. | `generated-semantics-v3.json`, `test_res541_a02_v3_generated_gold.py` |
| **Cache qualification read protected data.** It scored options on the first three held-out examples. | Qualification uses three training-split calibration examples (`TRAIN:541:2,5,7`). A spy backend shows only those are shown to the model before it passes, and none at all when it fails. | worker tests |
| **The plan understated the workload.** Pricing used the ten exposed cases (69 scorer calls); the held-out maximum is 73. | The bound comes from every request the worker scores. Nine sessions still hold, with 50.2 s of total slack. | `workload_scorer_calls`, plan tests |
| **The plan hash was not reproducible.** It covered the live quota rate, so the printed plan and the plan recomputed at run time differed, and no allowance could match. | The hash covers deterministic inputs only. | plan tests |
| **A stale preflight was accepted.** The only V3 receipt on E: predated V3.1. | The loader rejects a receipt for another profile; a fresh V3.1 receipt was written. | loader tests |
| **Teardown could stop a session the run did not create.** | Only a session this run attempted to allocate is stopped. | campaign tests |
| **Resume trusted committed records.** | Model id, revision, profile and protocol hashes, and the ordered work list, are verified before any new item. A re-chained forgery with valid hashes is refused. | worker tests |
| **Statistics were described too strongly.** The protocol said "the smaller lower bound governs". It governs only the adaptation-benefit gain; sufficiency compares point estimates. | The protocol now says so, and the report adds cluster design and single-arm lower bounds. The rule is unchanged. | decision tests |

## Gate evidence (CPU)

* **Full QA.** `./scripts/ci.sh`: ruff, format, mypy and repository policy pass, with no tracked mutation. Pytest: **1,706 passed, 3 skipped**. The skips are the real-decoder module (no torch in the default environment) and two offline-tokenizer tests.
* **Frozen identities.** `pyproject.toml`, `uv.lock` and `scripts/ci.sh` are byte-identical to the last pushed head `6a9f99b`. torch comes from the pinned overlay `experiments/a02/decoder-check-requirements.txt`.
* **Real-model decoder** (local receipt `v3-real-decoder-cpu-v2-bbbe820.json`). A tiny randomly initialised `SmolLM3ForCausalLM` (RoPE and NoPE layers), float32 on CPU, torch 2.14.1+cpu, transformers 4.53.0. **7 of 7 pass.** Cached and uncached option scores differ by at most **2.4e-5 nats** across four cases (the test tolerance is 2e-4; the in-run tolerance is 1e-3) with identical text and choice sequences. Removing the cache rollback fails 5 of 7 tests, including the end-to-end worker, which then stops at `QUALIFICATION_FAILED`. These tests skip in hosted CI.
* **Data.** 14 families; 2,800 training (200 per family) and 280 held-out (20 per family) examples; manifests `746cad1b…` and `ee0374a4…` match; leakage counts are all zero; every example is independently derived.
* **Decision rule.** The decision function rejects missing, duplicated, extra, reordered, relabelled, substituted, switched-arm and wrongly bound records, and any model, revision, profile, protocol or raw-output hash mismatch. Sufficiency and eligibility to study adaptation are distinct outcomes; no training is authorized.
* **Nine-session simulation.** The real worker, a simulated provider and a worst-case clock run all nine session slots. All 581 items are committed exactly once, in the plan's boundaries, and the result equals one uninterrupted run. Faults tested: torn writes, resume, forks, corrupted and duplicated records, missing records, identity and revision drift, live rate and spend increases, cost overrun, budget exhaustion, expired allowance, a pre-existing session name, a lost download and unconfirmed teardown. None is retried. Unrelated sessions are never stopped.

## Statistical honesty

The held-out set has **15 template clusters, about 8.1 effective** (cluster sizes 7 to 59), because several families share an objective template. Sufficiency compares the **point estimate** with 0.90. A point estimate of 0.93 on a plausible template-correlated outcome had an item-level lower bound of 0.896 but a template-clustered lower bound of 0.783 (two whole templates failing). Both bounds are reported with every decision and do not change it.

`ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING` is an engineering decision on same-generator development evidence. It is not a finding that the model is sufficient. If you want that wording to rest on the clustered bound, say so before authorizing: it is a threshold change and needs a protocol amendment.

## Execution design

* **Worker** (`a02_v3_worker.py`): 581 ordered, hash-pinned items — qualification, 280 held-out examples × two arms, then ten exposed cases × two arms. A hash-chained, fsynced checkpoint drops only a torn final line; every other inconsistency fails closed. The worker stops at an item boundary when the next worst case would pass the deadline.
* **Controller** (`a02_v3_execution.py`): pure admission against a live read-only quota snapshot and a V3-only ledger; a session marker consumed before allocation; exact-name T4 allocation with no retry; a rate and spend check before the work stage; checkpoint download even after failure; a fork-safe, identity-checked merge; exact-target teardown.
* **Campaign.** One expiring allowance replaces nine per-session authorizations. It can only tighten the plan, and every limit is rechecked each session. A campaign runs sessions back to back and **stops at the first anomaly without retrying**. Continuing is a deliberate new invocation.
* **Bootstrap** (`a02_v3_remote.py`): reviewed V2 primitives, then the worker.
* **Scoring:** CPU only, through `score_checkpoint`.

## Session and compute-unit plan

Plan hash `222330ffe63405f8d7524a676a1ab5e57e30cdabc30bc468e6cc81b7419ff99c`, from protocol `bbbe88bd…` and the V3.1 preflight `4b5c16f5…`. Receipts are on E: (`v3-session-plan-bbbe820.json`).

| Item | Worst case |
| --- | --- |
| Native action (128 tokens) | 7.4 s |
| Constrained action (73 scorer calls) | 4.65 s |
| Cache qualification (3 calibration examples, 219 uncached full forwards) | 145.35 s |
| All 581 items | 3,639.8 s of generation |

Per session: 720 s exec minus 180 s prepare, 100 s inference overhead and 30 s margin leaves **410 s** of generation inside a 900 s session. **Nine sessions give 3,690 s; slack is 50.2 s.** The nine-session maximum holds, narrowly, under worst-case bounds that are looser than every session-004 observation. Real runs are expected to need fewer sessions.

| Compute units | Value |
| --- | --- |
| Per-session cap | 0.3625 CU (900 s at the 1.25 CU/h ceiling + 0.05 buffer) |
| Cumulative cap | 3.2625 CU |
| Expected at the session-004 provider rate of 1.15 CU/h | 2.59 CU |
| Planning snapshot recorded earlier in this mission (not re-observed in this continuation) | balance 87.08 CU, rate 0.00 CU/h |

## Limits you are accepting

* The CPU qualification used a tiny random model in float32. It does not show that FP16 CUDA on a T4 keeps cached and uncached scores within 1e-3 nats. **If the in-run qualification fails, no arm result counts and that session's compute units are spent.**
* The cache is qualified once, in session 1. Later sessions run on fresh VMs and are not re-qualified; a per-session check does not fit nine sessions.
* Timing and cost are worst-case bounds from session 004, not V3 observations.
* Gold is checked against a project-authored adjudication of the generator's own phrasing. That checks the synthetic task's internal consistency, not whether real staff phrase requests this way.
* The zero-shot run collects actions only. Raw final grounding on the exposed cases is deferred.
* Results bound pinned SmolLM3 behaviour on one synthetic generator. They are not scientific generalization, real-request safety or PSE readiness.

## Owner decision

1. **Authorize or decline** one campaign allowance for the 9-session V3 zero-shot run. The allowance is a single file, written only by the owner, at `/mnt/e/DynamisLM-A0/a02/v3-zero-shot/campaign-allowance.json`. It binds the plan hash above and names `max_sessions` (at most 9), `cumulative_cap_cu` (at most 3.2625), `max_cu_per_session` (at least 0.3625), `valid_until_utc` with a timezone, and `allow_concurrent_unrelated_usage`. It does not exist. No GPU, training, paid upgrade or session 005 is requested.
2. **Keep or amend the sufficiency rule** before authorizing (see Statistical honesty). The default is to keep the preregistered rule.

The result can only adopt the repaired contract or make an adaptation experiment eligible. It cannot authorize training.
