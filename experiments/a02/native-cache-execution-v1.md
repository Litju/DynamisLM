# RES-541 prospective native-generation KV-cache execution amendment

The pinned SmolLM3 checkpoint config has `use_cache: false`. Its config SHA-256
`c72b1031274ff4626e434d0019e88e95a767460135db9ee492eb80652b786af1`
was verified against the actual GPU download and the immutable model revision.
The real full-FP32 diagnostic passed all three frozen TRAIN calibration examples,
101 candidate comparisons, original 0.001-nat gate and T4 memory checks, but native
generation inherited that disabled cache: 299.040428 seconds for123 tokens.
The controller stopped at a nonpaid campaign-budget planning gate. The T4 was
stopped and both inventories were empty. Conservative new cost0.3564167538277916 CU
remains charged to the original50-new-CU journal; historical0.2537 CU is separate.

Under the owner's explicit instruction to automate the campaign, train actual
weights and select an efficient finite budget, enable `use_cache=True` explicitly
for the prospective FP32 native-generation branch. Use math SDPA in that branch,
matching the already qualified cached scoring implementation. The checkpoint
config bytes are not edited. The legacy default/native-generation behavior remains
available when no cache choice is supplied. Model/revision, prompt/tokenizer,
examples/gold, greedy decoding (no sampling), ordering, scoring, thresholds and
0.001-nat tolerance remain unchanged. No quantization or alternate checkpoint.

This is a declared computational execution change before any of the580 baseline
evaluations, not an alteration of an observed baseline. Cached and full-context
conditional next-token likelihoods are mathematically equivalent. Actual FP32
cache parity has been measured; it does not prove universal bitwise or argmax
equality on every possible prefix. Tiny real-architecture generation tests must
verify cache activation, single-token incremental inputs, stable generated IDs,
FP32 logits, math attention and preserved legacy behavior. Every baseline session
also times native cached generation on frozen TRAIN before any held-out work and
refuses task execution if the projected resource bound is exceeded. The worker
then performs the unchanged in-run cached/reference qualification before tasks.

Planning keeps separate per-operation bounds. The cached-native projection uses
observed actual3B/T4 FP32 cached-tail forward times with a twofold margin, plus
full-context prefill and host-loop reserve. It is explicitly a projection until
the TRAIN admission measurement exists; the previous uncached rate is retained.
The TRAIN admission timing bound is charged to initialization in EVERY session,
not only the one-time qualification item. No FP16 timing is substituted.
Conservative whole-request cached scoring and
qualification costs are derived from the measured examples and frozen maximum
scorer-call bound. Persisted plans are hashed and independently re-derived.

Continuation preserves original grant.json, source.tar, diagnostic receipts,
charged costs, stopped planning result and terminal marker. A new source archive
and explicit continuation grant must reference those immutable artifacts. The
financial Budget object remains bound to the original grant and existing journal;
there is no new50-CU allowance and no diagnostic retry. Continuation is allowed
only when the sole prior paid session is a CLEAN successful diagnostic followed
by the recorded nonpaid resource-plan rejection. Kernel/precision/numerical/data
source bytes must match the qualified predecessor. The worker's AST must match
outside HFWorkerBackend.__init__/generate_native; the new native branch requires
fresh source qualification and independent review. A failed baseline, failed
training, unknown cost, changed evidence or incompatible source is not eligible.
Any subsequent paid anomaly remains terminal under the new continuation marker.
