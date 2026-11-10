# RES541-DR-003 — V3 zero-shot execution packet

## Control

`DECISION_ID=RES541-DR-003`

`STATUS=READY_FOR_OWNER_DECISION`

`GPU_ALLOCATED=NO` `SESSION_005_REQUESTED=NO` `TRAINING=NO` `V2_LEDGER_CHANGED=NO` `CAMPAIGN_ALLOWANCE_EXISTS=NO`

`DECISION_REQUESTED=AUTHORIZE_OR_DECLINE_ONE_FINITE_CAMPAIGN_ALLOWANCE_FOR_THE_V3_ZERO_SHOT_RUN`

This packet answers independent reviews #5824688227 and #5840002363 and the RES-541 continuation gates.
RES541-DR-002 remains the record of the V3 contract. Its 2,361 s estimate is superseded; the
engineering estimate is 2,735.7 s and admission uses the worst-case plan below. No V3 model
observation exists. Every figure here was produced on CPU. The Colab GPU path is unverified.

## What the continuation found and fixed

These are defects in the earlier local work, found by trying to falsify it:

| Finding | Fix | Evidence |
| --- | --- | --- |
| **Generated gold had no independent derivation.** The existing "agrees or fails closed" test passed vacuously: all 3,080 generated examples failed closed, so the generator was its own oracle. | A pinned closed-vocabulary adjudication of the complete generator phrasing, written from template text and not from family labels. All 2,800 training and 280 held-out gold actions now agree with it. `load_protocol` refuses any generator whose gold differs, even if the manifest hash is defeated, and names the failing example instead of skipping it. | `generated-semantics-v3.json`, `test_res541_a02_v3_generated_gold.py` |
| **Cache qualification read protected data.** It scored options on the first three held-out examples. | Qualification uses three training-split calibration examples (`TRAIN:541:2,5,7`). A spy backend shows only those are shown to the model before it passes, and none at all when it fails. | worker tests |
| **The plan understated the workload.** Pricing used the ten exposed cases (69 scorer calls); the held-out maximum is 73. | The bound comes from every request the worker scores. | `workload_scorer_calls`, plan tests |
| **The plan hash was not reproducible.** It covered the live quota rate, so the printed plan and the plan recomputed at run time differed and no allowance could match. | The hash covers deterministic inputs only. | plan tests |
| **A stale preflight was accepted.** The only V3 receipt on E: predated V3.1. | The loader rejects a receipt for another profile; a fresh V3.1 receipt was written. | loader tests |
| **Teardown could stop a session the run did not create.** | Only a session this run attempted to allocate is stopped. | campaign tests |
| **Resume trusted committed records.** | Model id, revision, profile and protocol hashes, and the ordered work list, are verified before any new item. A re-chained forgery with valid hashes is refused. | worker tests |
| **Sufficiency rested on point estimates.** With about 8 effective template clusters, a point estimate at 0.90 carries little independent evidence. | Amendment **P5 (V3.2)**: see "Decision rule" below. | decision tests |
| **Nine sessions left 50.2 s of slack.** One lost session, which is never retried automatically but still consumes its index, would have made completion impossible. | Amendment **P6 (V3.2)**: one reserve session; the plan builder refuses less than one whole session of slack. | plan and campaign tests |

## Decision rule (amendment P5, recorded before any V3 model observation)

The 0.90 overall and critical-family point thresholds are unchanged. Adoption now also needs the
**template-cluster-aware 95% lower bound** (the smaller of the item-level and template-clustered
percentile bounds, 10,000 resamples) to reach 0.90 on both the overall and the critical-family
exact rate of the zero-shot constrained arm.

| Evidence | Result |
| --- | --- |
| Both point thresholds and both lower bounds reach 0.90 | `ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING` |
| Both point thresholds pass, but a lower bound does not | `INCONCLUSIVE_INSUFFICIENT_INDEPENDENT_EVIDENCE`: neither adoption nor eligibility; adapted evidence cannot upgrade it |
| A point threshold fails on a complete, valid evaluation | `ADAPTATION_STUDY_ELIGIBLE_NOT_AUTHORIZED`: proposing a study becomes eligible; no training is approved and it is not evidence that adaptation would help |

Every decision reports: cluster design and critical-family cluster design (items, template
clusters, effective clusters); per-family performance with Wilson intervals; overall and
critical lower bounds for both arms; leave-one-template-out sensitivity; the limitations of the
bounds; and the scope `SYNTHETIC_DEVELOPMENT_ONLY`. No threshold may change after any V3 model
observation. The original rule is preserved verbatim in the amendment (superseded protocol
digest `bbbe88bd6b1e50afcfe43b9f17272e0e2f14b1cfb12eaa7723e49011eb31b632`) and in Git history.

Limits of the bounds: with about 15 template clusters (about 8 effective), percentile bootstrap
bounds are approximate and can be unstable when a few large clusters dominate; only template
dependence is modelled; and the bound describes this synthetic generator only. A realistic
consequence: an arm at 0.93 can be inconclusive. On the real held-out structure, losing two
whole reliability templates gives point 0.929 but an overall bound of 0.763; spreading errors
across templates at critical point 0.90 gives a critical bound of 0.861 while the overall bound
is 0.907.

## Gate evidence (CPU)

* **Full QA.** `./scripts/ci.sh` at code head `a64ab7e`: **1,717 passed, 3 skipped**. Ruff, format, mypy and repository policy pass, with no tracked mutation. The skips are the real-decoder module (no torch in the default environment) and two offline-tokenizer tests.
* **Frozen identities.** `pyproject.toml`, `uv.lock` and `scripts/ci.sh` are byte-identical to the last pre-continuation pushed head `6a9f99b`. torch comes from the pinned overlay `experiments/a02/decoder-check-requirements.txt`.
* **Real-model decoder** (local receipt `v3-real-decoder-cpu-v3-a64ab7e.json`). A tiny randomly initialised `SmolLM3ForCausalLM` (RoPE and NoPE layers), float32 on CPU, torch 2.14.1+cpu, transformers 4.53.0. **7 of 7 pass.** Cached and uncached option scores differ by at most **2.4e-5 nats** across four cases (test tolerance 2e-4; in-run tolerance 1e-3), with identical text and choice sequences. Removing the cache rollback fails 5 of 7 tests, including the end-to-end worker, which then stops at `QUALIFICATION_FAILED`. These tests skip in hosted CI.
* **Resource contention.** An earlier full-QA run failed one test with `OSError: Cannot allocate memory`. That test peaks at 294 MB, passes in isolation, and the host's committed memory exceeded its commit limit because of other tenants: contention, not an implementation defect.
* **Data.** 14 families; 2,800 training (200 per family) and 280 held-out (20 per family) examples; manifests `746cad1b…` and `ee0374a4…` match; leakage counts are all zero; every example is independently derived.
* **Decision binding.** The decision function rejects missing, duplicated, extra, reordered, relabelled, substituted, switched-arm and wrongly bound records, and any model, revision, profile, protocol or raw-output hash mismatch.
* **Nine-slot simulation.** The real worker, a simulated provider and a worst-case clock run all nine packed session slots. All 581 items are committed exactly once, in the plan's boundaries, and the result equals one uninterrupted run. One lost session is absorbed by the reserve (the run completes at index 10 after a deliberate new invocation); two lost sessions exhaust the allowance with evidence intact. Faults tested: torn writes, resume, forks, corrupted, duplicated and missing records, identity and revision drift, live rate and spend increases, cost overrun, budget exhaustion, expired allowance, a pre-existing session name, a lost download and unconfirmed teardown. None is retried; unrelated sessions are never stopped.

## Execution design

* **Worker** (`a02_v3_worker.py`): 581 ordered, hash-pinned items — qualification, 280 held-out examples × two arms, then ten exposed cases × two arms. A hash-chained, fsynced checkpoint drops only a torn final line; every other inconsistency fails closed. The worker stops at an item boundary when the next worst case would pass the deadline.
* **Controller** (`a02_v3_execution.py`): pure admission against a live read-only quota snapshot and a V3-only ledger; a session marker consumed before allocation; exact-name T4 allocation with no retry; a rate and spend check before the work stage; checkpoint download even after failure; a fork-safe, identity-checked merge; exact-target teardown.
* **Campaign.** One expiring allowance replaces per-session authorizations. It can only tighten the plan, and every limit is rechecked each session. A campaign runs sessions back to back and **stops at the first anomaly without retrying**; continuing is a deliberate new invocation.
* **Bootstrap** (`a02_v3_remote.py`) and **scoring** (`score_checkpoint`, CPU only) are unchanged.

## Session and compute-unit plan (amendment P6)

Plan hash `2dd513c65d3361d70a6c6ded6de7289a7152ea36d79112345ac417f0230c5aaf`, from protocol
`1a2e45763d5b0b81fdc40380965567a993208fb1040b995f6b01da963c333604` and the V3.1 preflight
`4b5c16f5…`. Amendment digests: P5 `5ef5d744d6851c48b9ed90e7a301d80a824881df3380f4fa1bac23ef0b4e5eb3`,
P6 `b527e2888b34c639315a3e1993d2b56b5f086cd128d4808f5c6a0a5fb009fc49`. Receipt on E:
`v3-session-plan-v32-a64ab7e.json`.

| Item | Worst case |
| --- | --- |
| Native action (128 tokens) | 7.4 s |
| Constrained action (73 scorer calls) | 4.65 s |
| Cache qualification (3 calibration examples, 219 uncached full forwards) | 145.35 s |
| All 581 items | 3,639.8 s of generation |

Per session: 720 s exec minus 180 s prepare, 100 s inference overhead and 30 s margin leaves
**410 s** of generation inside a 900 s session.

| Schedule | Value |
| --- | --- |
| Worst-case packed sessions | 9 (the earlier plan, 50.2 s of total slack) |
| Reserve sessions | 1 |
| **Sessions allowed** | **10** |
| Capacity / slack | 4,100 s / **460.2 s (12.6%)**, which covers one whole lost session |

| Compute units | Value |
| --- | --- |
| Per-session cap | 0.3625 CU (900 s at the 1.25 CU/h ceiling + 0.05 buffer) |
| **Cumulative cap (10 sessions)** | **3.625 CU** |
| Expected at the session-004 provider rate of 1.15 CU/h, nine packed sessions | 2.59 CU |
| Expected if all ten run | 2.88 CU |
| Planning snapshot recorded earlier in this mission (not re-observed in this continuation) | balance 87.08 CU, rate 0.00 CU/h |

Real runs are expected to need fewer sessions: the worker's deadline, not the packing, decides
where a session stops. The reserve is a ceiling to be spent only if a session is lost.

## Limits you are accepting

* The CPU qualification used a tiny random model in float32. It does not show that FP16 CUDA on a T4 keeps cached and uncached scores within 1e-3 nats. **If the in-run qualification fails, no arm result counts and that session's compute units are spent.**
* The cache is qualified once, in session 1. Later sessions run on fresh VMs and are not re-qualified; a per-session check does not fit the schedule.
* A calibration-only pilot before protected items would need a further session beyond ten; it is not built in. Session 1 proceeds into protected items when qualification passes.
* Timing and cost are worst-case bounds from session 004, not V3 observations.
* Gold is checked against a project-authored adjudication of the generator's own phrasing. That checks the synthetic task's internal consistency, not whether real staff phrase requests this way.
* The zero-shot run collects actions only. Raw final grounding on the exposed cases is deferred.
* Results bound pinned SmolLM3 behaviour on one synthetic generator. They are not scientific generalization, real-request safety or PSE readiness.

## Owner decision

**Authorize or decline** one campaign allowance for the V3 zero-shot run. The allowance is a single file, written only by the owner, at `/mnt/e/DynamisLM-A0/a02/v3-zero-shot/campaign-allowance.json`. It binds the plan hash above and names `max_sessions` (at most 10), `cumulative_cap_cu` (at most 3.625), `max_cu_per_session` (at least 0.3625), `valid_until_utc` with a timezone, and `allow_concurrent_unrelated_usage`. It does not exist. No GPU, training, paid upgrade or session 005 is requested.

The result can only adopt the repaired contract, be inconclusive, or make proposing an adaptation study eligible. It cannot authorize training.


## Final live-execution safety repair (review #5840002363)

The scientific contract, generated dataset, thresholds, model revisions, worker ordering and
V2 evidence remain unchanged. The exact commit and tree of the final published source must be
captured **outside Git**, in the owner campaign allowance's `source_identity` object, with keys
`commit` and `tree`. `source_identity()` refuses a dirty checkout. Each session rechecks this
identity before allocation; the session binding, consumed marker, campaign ledger and recovered
status bind it. The status binds the recovered checkpoint bytes by SHA-256, and checkpoint
adoption still checks the complete hash chain, prefix, work ordering and scientific identities.
The Git tree includes the protocol, model revision, runtime policy and required dependency
identities. There is no self-referential source hash in a repository artifact.

The reviewed V2 independent EOF/deadline watchdog must return READY before allocation. It runs
in its own process session, stops only the exact session on lost stdin/controller death or
900-second deadline, and writes a separate watchdog receipt. Disarm follows positive CLI and
authenticated provider-assignment absence verification. Stop, download and verification
exceptions are recorded separately so subsequent recovery and ledger writes are attempted.
The fake-CLI tests kill the actual parent process and exercise lost stdin without a real GPU.

Both `/content/a02-v3-status.json` and the checkpoint are requested from the exact session before
teardown, independently even after preparation or inference failure. Recovered bytes have
SHA-256 receipts. Successful work requires qualified READY runtime status. Missing, malformed,
misbound or inconsistent status cannot authorize checkpoint adoption. Remote stderr is bounded
and secret-like fields are redacted; failure stage and error type survive bootstrap failures.
Failed download, runtime/CUDA qualification or preparation is an execution anomaly, never a
scientific model NO_GO.

During remote stages, a five-second poll uses the V2 conservative maximum of account balance
delta and elapsed-rate cost, remaining cumulative allowance and a cleanup/poll reserve. Rate
changes, unknown quota, unexpected session inventory and ambiguous attribution stop the exact
target. Provider snapshot checks reconcile authenticated CLI, usage and provider assignments.
Concurrent billed usage is refused even if an allowance requests it. Unknown final quota
records a conservative over-cap ledger value and blocks continuation. Every anomaly ends the
automatic campaign; any later invocation is a deliberate operator action consuming another slot.

Owner decision remains one expiring campaign for **only ZERO_SHOT_UNCONSTRAINED and
ZERO_SHOT_CONSTRAINED**, at most **10 T4 sessions**, **900 seconds each**, **0.3625 CU/session**,
**3.625 CU total**, with no training, upgrade or uncontrolled retry. The authorization must name
the exact final source commit/tree and existing plan hash, expire with a timezone, and set
`allow_concurrent_unrelated_usage=false`. No allowance is created by this repair. Historical QA
receipts above describe earlier heads; final repair QA/CPU and exact-head hosted CI are linked
in the PR and Linear completion update. Independent scientific/adversarial review remains a
merge requirement. All scientific claims remain **SYNTHETIC_DEVELOPMENT_ONLY**.
