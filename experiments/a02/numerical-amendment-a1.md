# RES-541 prospective A1 numerical amendment

Status: PROPOSED, NOT ACCEPTED. This file grants no execution, expenditure,
experiment, or merge authority. The original V3 protocol remains immutable.

Sessions 003 and 004 failed the frozen 0.001-nat absolute option-likelihood
qualification: maxima 0.0597076304 and 0.0481757927 nats respectively. Their
matching selected actions do not satisfy likelihood equivalence. All four
historical sessions retain their original failed dispositions and evidence;
historical conservative cumulative expenditure is 0.2537 CU. Scientific task
evaluations remain 0/580.

Three mathematically equivalent paths score the identical token suffix:
A recomputes full context; B creates a fresh prefix cache for each candidate;
C crops and reuses the production cache. B uses C's chunk boundary. A/B tests
execution-shape differences; B/C additionally tests reuse history. Tiny randomly
initialized real SmolLM3 architecture tests exercise RoPE/NoPE layers, masks,
position indices, shared-prefix rollback, scored-token alignment and adversarial
stale-cache, crop-offset and target-offset defects. Scaled synthetic logits in
FP16 reproduce tolerance violations even with a fresh cache; FP32 passes these
CPU tests. Layer tracing and projection decomposition locate rounding within
the transformer and projection. This supports an arithmetic explanation; it
does not establish the production cache's correctness on the pinned 3B T4 model.

A1 proposes loading the SAME checkpoint revision in FP32, applying FP32 to both
cached/reference scoring and both native/constrained comparison arms. Loading
BF16-stored values into FP32 cannot recover checkpoint storage precision. It
reduces subsequent arithmetic rounding only. TF32 and autocast are disabled,
matmul precision is highest, and parameter, floating-intermediate, KV and logit
dtypes are inspected. The existing math SDPA scoring backend is retained. The
historical FP16 loader remains selectable. Log-softmax remains FP32 and score
accumulation uses Python double precision as in the cached scorer.

Frozen identities: HuggingFaceTB/SmolLM3-3B at
`a07cc9a04f16550a088caea529712d1d335b0ac1`; the V3 protocol, prompt/tool bytes,
tokenizer, examples, gold, evaluation order, scoring, decisions and 0.001-nat
qualification tolerance are unchanged. There is no model upgrade, training,
quantization, alternative checkpoint or relaxed acceptance. Different FP32
rankings, if observed, must be reported prospectively, never substituted into
historical results.

Acceptance is staged. The owner must explicitly accept A1 for one diagnostic
and separately approve the exact clean commit/tree/archive, protocol and this
amendment's hash in a finite one-session authorization. Independent targeted
review and exact-head CPU/hosted QA precede paid execution. The diagnostic uses
only the three frozen TRAIN calibration examples, starting with one; OOM,
non-finite values, numerical failure or resource anomaly ends the attempt
without retry. Full-model/T4 fit and 0.001-nat qualification remain unverified.
A successful diagnostic permits only preparation of a measured campaign
proposal. Experiment use of A1 and the full 580-item campaign need separate
owner acceptance and budget; no task evaluation is authorized by this file.
