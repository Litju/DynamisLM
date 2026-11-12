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
