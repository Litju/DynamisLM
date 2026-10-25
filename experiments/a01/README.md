# RES-541 A0.1 CPU qualification

This is `A0.1_PROMPT_V1`, a prompt-only development experiment using the unchanged
`RES541_A0_INTENT_V1` parser and registered Python authority. A0 remains scientific
**NO_GO**. This directory authorizes no GPU allocation, Colab launch, model weights,
training, merge, or release. The existing A0 launch command still runs **A0**.
The rendered A0.1 prompts are review artifacts for a separately owner-approved run;
this CPU command never loads or executes a language model. The separate
`scripts.a01_execution` adapter below now supplies the A0.1 execution path.

## Reviewed scope

The [architecture decision](../../docs/experiments/RES-541-A01-INTERFACE-DECISION.md)
and live RES-541 issue govern this experiment. Original source, 16-case manifest,
parser, scientific operations, checkpoint revision, greedy/FP16 policy and
1,024-input/64-output ceilings are unchanged. `freeze-v1.json` pins the separately
versioned prompt, controls, original files and exact tokenizer assets. Qualification
also compares all A0 scripts, fixtures, historical tracked reports and scientific
source against `a7216366e46c3a80bd20435a6d894e917d90e5f0`.

The local eight-example candidate is preserved at its original E: location and
SHA-256 `f65c82b31c433370154ed601a4a884ff7904ee297a9e9a484d1679997227291e`.
Its examples parse, and the actual tokenizer measures its 16 full inputs at
858–869 tokens. Its refusal examples describe absent evidence and excessive claims
as unrepresentable, conflicting with the decision's routing boundary. The new
prompt states `EXECUTE = SUBMIT_FOR_AUTHORIZATION`, lists the actual enum sets,
defines row absence versus missing values, and reserves REFUSE for unmappable
requests. Three concrete demonstrations cover valid change, missing-value change,
and an unmappable poem request. All parse using the actual production parser.
The smaller demonstration set leaves room for the explicit enum/routing contract;
no token limit was raised.

## Synthetic control provenance

The original 16 cases are exposed diagnostic development cases. Their replay is
not evidence of untouched generalization. The 12 active controls in
`controls-v2.json` were authored separately with different requests and value pairs,
before any A0.1 model output. Expectations were specified before checking them
against canonical authority. They reuse existing synthetic constructors and the
same author; they are neither blinded independent adjudication nor a benchmark.
No PSE sources, seeds or outputs were consulted.

`controls-v1.json` preserves an unsuccessful authoring revision. Its all-missing
case cannot construct `StatisticalSupport` because included entries must be
nonempty. That remains an explicit negative test and is **not** counted as a
canonical scientific refusal. V2 retires that case and adds a separately authored
metric-identity control; it does not change the retired case's expected result.
Both revisions and the active selection are hashed before model generation.

The supplied-intent CPU checks validate 4 numerical results and 8 final canonical
refusals on the active controls. Causal intent reaches a calculation followed by
**PARTIALLY_AUTHORIZED** claim authority and final refusal of the requested causal
claim. Preserve this distinction. These checks supply oracle intents; they are
not measurements of model performance.

## Reproduce on WSL CPU (E: only)

Start in the existing RES-541 worktree. Use its existing Python 3.12 environment.
The tokenizer environment installs only pinned packages, with `--no-deps` to avoid
pulling a tensor framework. Only four explicitly named tokenizer assets are fetched
from the pinned checkpoint; weights and model configurations are never requested.

```bash
test "$(findmnt -n -o SOURCE --target /mnt/e)" = 'E:\'
mkdir -p /mnt/e/DynamisLM-A0/{a01,cache/{uv,pip,xdg,huggingface,torch,ruff,mypy,pytest},tmp}
export TMPDIR=/mnt/e/DynamisLM-A0/tmp
export UV_CACHE_DIR=/mnt/e/DynamisLM-A0/cache/uv
export PIP_CACHE_DIR=/mnt/e/DynamisLM-A0/cache/pip
export XDG_CACHE_HOME=/mnt/e/DynamisLM-A0/cache/xdg
export HF_HOME=/mnt/e/DynamisLM-A0/cache/huggingface
export TORCH_HOME=/mnt/e/DynamisLM-A0/cache/torch
export RUFF_CACHE_DIR=/mnt/e/DynamisLM-A0/cache/ruff
export MYPY_CACHE_DIR=/mnt/e/DynamisLM-A0/cache/mypy
export PYTHONDONTWRITEBYTECODE=1
export USE_TORCH=0 USE_TF=0 USE_FLAX=0
export PYTEST_ADDOPTS='--capture=sys -o cache_dir=/mnt/e/DynamisLM-A0/cache/pytest --basetemp=/mnt/e/DynamisLM-A0/tmp/pytest-a01'
uv venv --python .venv/bin/python /mnt/e/DynamisLM-A0/a01/tokenizer-venv
uv pip install --python /mnt/e/DynamisLM-A0/a01/tokenizer-venv/bin/python --no-deps -r experiments/a0/requirements-colab.txt
unset PYTHONPATH PYTHONHOME
TOKENIZER_SITE_PACKAGES=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages
PYTHONPATH="$TOKENIZER_SITE_PACKAGES" .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    'HuggingFaceTB/SmolLM3-3B',
    revision='a07cc9a04f16550a088caea529712d1d335b0ac1',
    local_dir='/mnt/e/DynamisLM-A0/a01/tokenizer', token=False,
    allow_patterns=['tokenizer.json', 'tokenizer_config.json',
                    'special_tokens_map.json', 'chat_template.jinja'],
)
PY
PYTHONPATH="$TOKENIZER_SITE_PACKAGES" \
RES541_A01_TOKENIZER_DIR=/mnt/e/DynamisLM-A0/a01/tokenizer \
  .venv/bin/python -m pytest -q tests/test_res541_a0.py tests/test_res541_a01.py
PYTHONPATH="$TOKENIZER_SITE_PACKAGES" .venv/bin/python -m scripts.a01_experiment \
  --tokenizer-dir /mnt/e/DynamisLM-A0/a01/tokenizer \
  --baseline-report /mnt/e/DynamisLM-A0/reports/res541-a0-20261023-040456z-report.json \
  --postmortem-dir /mnt/e/DynamisLM-A0/reviews/res541-a0-20261023-040456z-postmortem-v1 \
  --output /mnt/e/DynamisLM-A0/a01/cpu-qualification-HEAD.json
./scripts/ci.sh
```

Choose a new receipt filename on each run; existing receipts cannot be overwritten.
`--capture=sys` avoids WSL E: temporary-file descriptor capture failures. Hosted CI
runs the portable contract tests; the actual tokenizer/postmortem integration test
requires the explicit E: environment and is skipped on hosts lacking those assets.
Hosted CI therefore complements the E:-local qualification receipt.
CI fetches Git history so the original A0 commit comparison runs on hosted workers
as well as the existing WSL checkout.
Full QA runs in the repository's frozen environment, without the separate tokenizer
environment on PYTHONPATH. Exposing optional inference libraries to mypy changes
its dependency discovery and invalidates existing missing-import annotations.

Keep the tokenizer site-packages scoped to individual host Python commands; never
globally export that `PYTHONPATH` before calling Colab. The pinned tokenizer uses
filelock 3.18.0, while installed Colab CLI 0.7.5 requires filelock >=3.29.2.
The A0.1 adapter copies the host environment and removes `PYTHONPATH` and
`PYTHONHOME` for **every** Colab child: interactive/captured quota checks, run,
download, stop and sessions. The host tokenizer process retains its pinned
packages. E: cache/download/temporary-directory settings and OAuth configuration
remain available to the CLI; neither dependency environment is upgraded.

For direct non-GPU CLI checks, after configuring E: paths above, use:

```bash
env -u PYTHONPATH -u PYTHONHOME colab --auth=oauth2 sessions
env -u PYTHONPATH -u PYTHONHOME colab --auth=oauth2 usage
```

The receipt records package versions, source and file hashes, actual official chat
template (`enable_thinking=False`), complete lengths and token-ID hashes for all 16
diagnostic inputs and all 12 active controls, and all intended output lengths with
one EOS token. The template injects its execution date. Each exact rendered prompt
is retained locally, including metadata/date, so a later date cannot silently
change this receipt. Retokenize its `rendered_prompt` with `add_special_tokens=False`
and hash compact JSON token IDs to reproduce each recorded token hash. The CPU
command fails on asset/hash/version drift or either unchanged token ceiling.

The original report SHA-256, all scorer-produced fields and every forensic case's
overlapping classifications are recomputed independently. All postmortem files
are checked against their existing SHA256SUMS and rehashed after the read-only
check. Neither original report nor local postmortem is rewritten or published.

## Separate measurements for an approved A0.1 run

`observe()` traces direct calls from the existing engine, recording analysis
authorization, registered calculation (including its hash even when a subsequent
claim is denied), and claim authority status/reasons/hash. Internal validation
replays are excluded from submission counts. Raw JSON validity, strict typed
validity, semantic intent exact match, parser fallback, raw REFUSE strings, typed
model refusal, canonical refusal, numeric integrity, unauthorized calculation and
final safety have separate counters. A parser fallback is never a model or
scientific refusal success. Precision/integrity rates with no eligible outputs
are native null. All active cases are representable; a typed model refusal is
therefore an incorrect unmappable classification on these suites.

The CPU scorer accepts an external V1 model-output document only with pinned model
identity, `prompt_version=A0.1_PROMPT_V1`, `system_prompt_sha256` matching the freeze,
and the exact case-ID set for the selected suite. It preserves raw output and
inference metadata and never repairs invalid intent. Once such outputs exist:

```bash
.venv/bin/python -m scripts.a01_experiment \
  --score-model-outputs /mnt/e/DynamisLM-A0/a01/approved-model-outputs.json \
  --suite a0_diagnostic \
  --output /mnt/e/DynamisLM-A0/a01/diagnostic-layered-score.json
```

Use `--suite a01_controls` for a separate 12-case control output artifact. This does
not authorize combining suites into a larger GPU allocation. No A0.1 model output,
latency, GPU memory, scientific accuracy or generalization result exists yet.
CPU readiness additionally requires successful hosted CI at the exact pushed head.
The owner must separately approve any subsequent Colab experiment; stop before
requesting GPU allocation.

## Explicit execution adapter (not launched during implementation)

Execution protocol: `RES541_A01_EXECUTION_V1`. The adapter loads exactly
`A0.1_PROMPT_V1` / SHA-256
`3a427cbddec385a60e2843f921d3b8a3e3d0b80af8167f12a71a4d07a5639362`.
The reviewed freeze manifest itself is also hash pinned. Original A0 source,
reports, cases, scientific contracts and `tests/fixtures/a0/` remain immutable.

The new remote entry downloads only the SHA-verified original bootstrap source
from the approved Git revision, then reuses its exact source checkout, Python
3.12 scientific environment, Python 3.13/Torch environment, T4 preflight and bounded
subprocesses. It redirects only preparation, inference and scoring to A0.1 modules.
The inference adapter creates a private instance of the frozen A0 module and
substitutes the verified A0.1 prompt plus token-capture hooks. Original A0 modules
and their behavior remain unchanged. The inherited inference loop preserves the
checkpoint, FP16, greedy decoding, non-thinking mode and 1,024/64 token bounds.
All four remote tokenizer assets are SHA-verified before model loading.

After separate owner review/authorization, in an interactive WSL terminal with
the E: environment shown above, select **one** command. Scope the tokenizer path
to the host adapter process; its Colab children use the isolated environment:

```bash
# Proposal: 16 exposed diagnostics, one T4, run <=900 s plus bounded cleanup.
env -u PYTHONHOME \
  PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages \
  .venv/bin/python -m scripts.a01_execution run --suite a0_diagnostic --cases 16 \
  --output-dir /mnt/e/DynamisLM-A0/reports/a01/diagnostic \
  --tokenizer-dir /mnt/e/DynamisLM-A0/a01/tokenizer

# Alternative: 12 frozen controls, one T4, run <=900 s plus bounded cleanup.
env -u PYTHONHOME \
  PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages \
  .venv/bin/python -m scripts.a01_execution run --suite a01_controls --cases 12 \
  --output-dir /mnt/e/DynamisLM-A0/reports/a01/controls \
  --tokenizer-dir /mnt/e/DynamisLM-A0/a01/tokenizer
```

Use `.venv/bin/python` for the existing WSL project environment. These are separate
proposals, not authorization to execute both. There is no combined 28-case option,
noninteractive approval flag, retry or GPU fallback. Each invocation requires a
clean pushed mission revision, actual tokenizer fit, positive fresh Colab quota,
zero active assignments and an exact interactive confirmation containing source,
prompt, manifest, suite, actual count, available quota, T4, 900 seconds, 8 GiB
weight-download ceiling, token limits and download/stop/verification timeouts.
The 900 seconds bounds the run command; retained-session download and teardown
are additional bounded time and can consume GPU quota until stop succeeds.
Source and suite are rechecked after
confirmation. A host watchdog also bounds the Colab run process to 900 seconds.

Remote inference records every actual prompt token ID/hash, UTC template date,
user-message hash, generated token ID, untrimmed decoded raw output, count and
per-case binding hash. Each binding includes exact source revision/tree, model
and tokenizer revision, prompt version/hash, frozen manifest, suite and decoding
limits. Missing evidence, foreign IDs, altered provenance, incompatible GPU/dtype,
missing EOS and generations hitting the output cap are rejected. Partial raw
generations survive inference failures and temporary-directory cleanup.

The remote score is provisional (`HOST_REPLAY_REQUIRED`). After retrieval the
host leaves the remote artifact untouched, independently re-renders each prompt
using the pinned official tokenizer and its recorded date, decodes the actual
generated IDs, validates every binding and invokes the existing layered scorer.
The downloaded scientific score must exactly equal this CPU replay after JSON
normalization. Invalid model intent remains a measured parser fallback and causes
task NO_GO; it is never repaired. The old standalone CPU scorer remains useful
for exploratory raw-output diagnostics; only the execution adapter performs this
full production-evidence acceptance gate.

Download (120 s), stop (30 s) and session-list (30 s) calls run in nested cleanup
even on launch, run, or download errors. Acceptance requires a successful stop
and an explicit **zero active sessions** response, including absence of other
sessions. Unknown output fails closed with a control receipt and manual stop
command. Host downloads, raw artifacts, control receipts and verified reports
remain under mounted E:. Weights and remote caches remain ephemeral on Colab.

CPU-only adapter validation (including actual tokenizer replay when available):

```bash
env -u PYTHONHOME \
  PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages \
  RES541_A01_TOKENIZER_DIR=/mnt/e/DynamisLM-A0/a01/tokenizer \
  .venv/bin/python -m pytest --capture=sys \
  --basetemp=/mnt/e/DynamisLM-A0/tmp/pytest-a01-adapter \
  -q tests/test_res541_a01_execution.py
env -u PYTHONPATH -u PYTHONHOME ./scripts/ci.sh
```

Tests use synthetic CPU model doubles, including whitespace/partial generations;
they do not measure model performance or prove live Colab operation. The exact
pinned tokenizer is exercised separately on all 16+12 inputs. GPU allocation,
weights and actual inference remain separately owner gated.
