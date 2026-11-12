# RES-541 owner-delegated execution — prospective operational amendment

The owner explicitly approved the A1 diagnostic and requested automatic campaign
launch and actual trained weights, then delegated CU-budget selection to the
agent. The original source-bound 0.26-CU proposal and approval remain historical;
they are not edited. The owner conversation and selected limits are recorded
outside Git in `owner-delegated-budget-50cu-v2.json` under the A1 evidence root.
This document is an execution specification, not a substitute for that receipt.

The selected hard ceiling is 50 NEW CU, with historical 0.2537 CU separate. It is
not a spending target. All stages require a source-bound plan and conservative
cost admission. The actual pinned-model diagnostic must pass before any of the
580 baseline evaluations; the baseline is preserved before training. Subsequent
campaign limits must be computed from measured FP32 throughput, not the old FP16
estimate. Training is owner-requested prospective LoRA work on the frozen 2,800
TRAIN examples only. The original study's decision rule and dispositions remain
intact; training does not retroactively make an inconclusive result eligible or
prove a benefit. Trained weights and their model/data/source hashes must be
recovered outside Git, and training success must be distinguished from measured
scientific improvement.

## One diagnostic with observed pricing

Read-only authenticated `/tun/m/ccu-info` reports current account consumption and
GPU eligibility. It exposes neither a preallocation T4 rate quote nor a minimum
startup-charge quote. No historical rate or idle rate is relabelled as a quote.

For the delegated diagnostic only, the maximum new cap is 3 CU. Keep one T4,
1,800-second independent watchdog, 90-second stop reserve, and no retry. Before any
upload, model download or model loading, record the actual post-allocation rate
and initial account-balance delta. Admit no model work above 4 CU/hour or an
initial delta above 0.15 CU. Require the conservative modeled bound
`1890 * observed_rate / 3600 + initial_delta + 0.05 <= 3 CU`.
At both admission ceilings this is 2.3 CU. The initial delta is a conservative
observed account amount, not an independently verified minimum startup charge.
The live monitor continues throughout prepare/work, and final cost is at least
the full account delta. Unknown pricing, cost, resource state, non-finite values,
OOM, numerical failure or teardown failure stops the attempt. A provider charging
an unexpected upfront amount can breach an assumed allowance before it is
observed; such a breach is recorded as failure and blocks downstream execution.
The delegated 50-CU envelope is not permission to conceal or ignore that anomaly.

The CLI's internal assignment POST retry count is explicitly zero. A grant-wide
single-use diagnostic marker prevents retries by regenerating a proposal hash.
The original verified-price diagnostic mode remains unchanged and available for
historical source inspection. Both modes require exact clean source, archive,
protocol, numerical-amendment and proposal bindings plus owner authority.

The model and revision, FP32 numerical contract, prompts, data, labels, scientific
thresholds, evaluation ordering, math SDPA scorers and 0.001-nat tolerance are
unchanged. This operational amendment grants no alternate checkpoint,
quantization, paid hardware upgrade, held-out training or automatic retry.

## Automatic baseline and learned-weight artifacts

After successful real-model qualification, the automatic controller constructs a
new source-bound FP32 baseline plan from the observed native token rate, cached
scoring times and full-context forward times, with conservative twofold timing
margins and a reserve session. The original 581-item work order and scoring are
unchanged. Baseline sessions are bounded to 3,600 seconds, with 300 seconds for
cleanup; this is a prospective operational extension of the original 900-second
execution plan, not a rewrite of that historical plan. Any no-progress session,
price/cost anomaly, missing precision proof or failed teardown stops the pipeline.

Only after the complete baseline is scored may the owner-requested LoRA study
start. Training sessions are bounded to 7,200 seconds with 600 seconds for recovery
and cleanup. All phases share the same 50-new-CU journal, bound to one fixed
owner-receipt directory, with at most 64 sessions in total and no automatic retry.
Session caps and the complete campaign count are derived before admission; the
journal cannot erase unknown or over-cap cost by starting another proposal.

Training retains the protocol's rank16/alpha32/dropout0.05 q/k/v/o adapters,
2 epochs, AdamW lr0.0002, warmup0.03, full-input batch-token budget16384 and seed541.
The explicit T4 execution choices are: frozen FP16 base, trainable FP32 adapters,
FP16 autocast with an initial loss scale of128, math SDPA for forward AND checkpoint
recomputation, non-reentrant gradient checkpointing, microbatch1, mean target-token
cross-entropy gradients, tokenizer EOS appended to target_text, norm clipping1,
AdamW betas(0.9,0.999)/epsilon1e-8/decay0.01, linear warmup/decay and deterministic
seed+epoch shuffling. Nonfinite values and skipped optimizer updates stop training.
These are prospective implementation choices; evaluation remains full FP32.

Optimizer, scheduler, scaler and CPU/CUDA RNG states are checkpointed at complete
step boundaries. Adapter and base invariants, example order, source/profile/data
hashes, weight fingerprints and recovery archives are checked. CPU tests must show
that learned tensors change, base weights remain frozen, loss indexes only target
next-token positions, exports reload and resumption matches uninterrupted updates.
Final adapter tensors, config and provenance are recovered outside Git. Training
loss is never substituted for held-out scientific accuracy or adaptation benefit.
