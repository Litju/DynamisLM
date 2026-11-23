# A0.3 paired evaluation operation

The registered scientific rules are in [prospective-protocol.md](prospective-protocol.md).
This implementation separates blinded generation from adjudicated dispatch. The runner
never takes a gold or adjudication path. Give its operating identity only the blinded input
and output paths. After the custodian archives the complete output bytes and commitment,
a separate scorer identity can receive the packet. Local credentials or file permissions
held by the same operator do not establish independent custody.

## Blinded generation

Use a clean exact checkout and private directories outside Git. The custodian exports each
registered request through `a03_prospective_run.blind_request`, in frozen order, as
`requests.jsonl`. The trusted resolver supplies a matching `sources.jsonl` with
`item_id` and `bound`, where `bound` is canonical Serialization V3 JSON text for a
`BoundRequest`. Qualified observations bind the immutable source digest, canonical
longitudinal record and observation digests, exact device, protocol and unit. Unresolved slots
follow the qualified prefix and are omitted from the model prompt.

Use `run_manifest(PROSPECTIVE, requests_bytes, source_bytes)` and store the canonical
object in `run.json`. Exchange its exact byte SHA-256 through the custodian's authenticated
channel. The model snapshot and adapter must already be local and match the D0 file pins.
The entry point is:

```text
python -m scripts.a03_prospective_run BLIND OUTPUT --manifest-sha256 DIGEST \
  --snapshot MODEL_SNAPSHOT --adapter STEP_510 --device cuda --seconds SECONDS
```

Resume only with the externally retained digest of an intact prefix. Torn checkpoints
stop without truncation. An output commitment appears only after all arm rows are present.
The host must adopt the checkpoint and commitment into the external append-only archive.

## Gold release and scoring

The custodian supplies `release.json` outside the blinded directory and an authenticated
exact byte digest. The release binds schema `DYNAMISLM_A03_GOLD_RELEASE_V1`, mode
`PROSPECTIVE`, `output_commit_sha256`, the existing sealer receipt as `packet`, and
the exact digest of `custodian-attestation.json` as `custodian_attestation_sha256`.
The signed attestation and authenticated delivery are the external authority for human
independence, source rights, exposure checks and custody. The scorer checks their binding.

```text
python -m scripts.a03_prospective_score BLIND OUTPUT RELEASE REPORT \
  --manifest-sha256 DIGEST --commit-sha256 DIGEST --release-sha256 DIGEST \
  --tokenizer MODEL_SNAPSHOT
```

The scorer verifies the committed output first, then reproduces the registered seal.
It replays each model action through RES-70 with an additional veto immediately before
dispatch. If the adjudicated control forbids the attempted operation, the scorer records
the first violation and stops before that operation runs. The result retains per-item
traces, endpoints, paired contrasts and cluster estimates. No final-answer metric exists.
The scripted CPU fixture exercises these paths without model weights under
`DEVELOPMENT_ONLY`, which never emits a prospective study decision.

## RES-746 real-model development qualification

Use the fixed two-item workload from `scripts.a03_real_model_qualification`. It
reconstructs the exposed RES-747 synthetic absolute-change demo with two qualified
observations. It also reuses the question from D0 case `HELDOUT:5410:62` with an
unresolved source slot. The model sees an empty trusted snapshot for that case, so
its rendered prompt differs from historical D0. The six arm calls use the paired
order and checkpoint format above. The qualification verifier replays the output
commitment and invokes RES-70 on the generated proposals and on causal and practical
escalation controls. It takes no gold and produces no study decision.

In a clean exact checkout, use a private directory outside Git with `blind` and `out`
subdirectories of mode 0700. Set `PYTHONPATH` to the checkout's `src` and
`PYTHONNOUSERSITE=1`. Set `PY` to the runtime interpreter and `SNAPSHOT` and
`ADAPTER` to local directories containing the individually verified files in
`a03_d0_runtime.py` and `experiments/a02/tokenizer-files-v1.json`. Stage only those
files and Hugging Face download metadata in `.cache`, since other model and tokenizer
files can override the loader's selection. There is one unquantized numerical profile,
FP32 with MATH SDPA and TF32/autocast disabled. CPU qualification uses CPython 3.13,
`torch==2.14.1+cpu` from the PyTorch CPU index and the existing pinned D0
requirements from `experiments/a0/requirements-colab.txt` and
`experiments/a02/training-requirements-v1.txt`. Install `pytest==8.4.2` and
`openpyxl==3.1.5` for the repository modules imported by the historical sample.
Record the runtime package
inventory, CPU model and the thread settings. A CPU run establishes only CPU behavior.

```sh
umask 077
export PYTHONPATH="$PWD/src" PYTHONNOUSERSITE=1
MANIFEST=$("$PY" -m scripts.a03_real_model_qualification prepare "$BLIND" --device "$DEVICE")
timeout --kill-after=10s "$WALL" "$PY" -m scripts.a03_prospective_run "$BLIND" "$OUT" \
  --manifest-sha256 "$MANIFEST" --snapshot "$SNAPSHOT" --adapter "$ADAPTER" \
  --device "$DEVICE" --seconds "$SECONDS_BOUND" --stop-after 1
```

Save the returned `prefix_sha256` outside the runner's writable state and rerun the
same command with `--resume-sha256` and without `--stop-after`. A generation deadline
leaves the qualification prefix intact and allows the unfinished row to be retried.
An outer watchdog bounds the whole process, including setup and any uninterruptible
model operation. A hard kill can leave a torn tail, which requires custody
disposition. After completion, retain the exact SHA-256 of `output-commit.json`
outside the output directory and verify on the same source checkout:

```sh
"$PY" -m scripts.a03_real_model_qualification verify "$BLIND" "$OUT" \
  --manifest-sha256 "$MANIFEST" --commit-sha256 "$COMMIT_DIGEST" --tokenizer "$SNAPSHOT"
```

### One T4 session proposal

Before approval, archive a clean shallow checkout (including its Git metadata)
from the candidate head, with the exact checkout SHA-256, CUDA `run.json`, two JSONL
input files and pinned step-510 adapter. Record hashes for the transferred archives,
manifest, rendered prompts and work order. Verify those at setup and persist the
authenticated approval of that proposal digest before allocation. The existing D0
allocation is closed. Confirm the account is idle and the requested session name
is unused in both authenticated inventories. Arm the existing `D0Colab` watchdog
for the named session before requesting the single T4. Use the D0 supervisor
primitives in `scripts/a03_d0_colab.py` for monitoring and exact-target teardown.
Do not invoke the historical D0 launcher for this workload.

- Limit to one allocation and 3,600 seconds from the start of allocation through
  verified absence. Arm the watchdog at 3,420 seconds. Budget at most 1.15 CU/hour
  and 0.20 CU reserve, with a 1.35 CU modeled cap from existing balance and zero
  new purchases. Check the live rate and inventory before upload and at least
  every five seconds during work. Stop on a mismatch, a cost overrun, a failed
  watchdog check or an incomplete budget. No retry allocation or extension.
- Use an isolated CPython 3.13 inference environment inheriting the provider's
  `torch==2.14.1+cu130`. Follow the existing setup commands in
  `a03_d0_colab_bootstrap.py` through the requirements installation. Install the
  same pinned pytest and openpyxl as on CPU. Check CUDA 13.0,
  T4 compute capability 7.5 and at least 14 GiB free VRAM before load. Stage at most
  20 GiB of local disk for pinned weights, libraries and evidence. D0 measured
  12.56 GiB peak CUDA reserve for N/C1, which informs planning for C0.
- Allow 1,800 seconds for upload, setup and download of the pinned base snapshot,
  including the verified source, adapter and environment. Use the remaining
  session time only if it covers all three bounded runner invocations and a
  separate 120-second teardown reserve before watchdog expiry. Bound the process
  invocations to 240, 240 and 480 seconds including model loads. Use `--seconds 120
  --stop-after 1`, resume the intact one-row prefix with `--seconds 0.10` without a row
  cap to test the generation deadline, and resume that same prefix with
  `--seconds 360` for completion. Require the deadline attempt to leave the prefix
  and row count unchanged. Stop on failure and retain partial evidence.
- Reserve 60 seconds before teardown for transferring raw checkpoint rows, their
  commitment, the runtime receipt, per-invocation measurement receipts and logs.
  Save the digests on the host, delete the remote workspace and stop the exact
  target in a finally path. Verify absence from the terminal and resource
  inventories, and recheck zero active assignments and zero usage rate before
  disarming the watchdog. Record balance before and after, modeled CU and elapsed
  time. The displayed balance and modeled CU are distinct evidence.
