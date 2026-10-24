# RES-541 A0.1 CPU qualification

This is `A0.1_PROMPT_V1`, a prompt-only development experiment using the unchanged
`RES541_A0_INTENT_V1` parser and registered Python authority. A0 remains scientific
**NO_GO**. This directory authorizes no GPU allocation, Colab launch, model weights,
training, merge, or release. The existing A0 launch command still runs **A0**.
The rendered A0.1 prompts are review artifacts for a separately owner-approved run;
this CPU command never loads or executes a language model.

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
export PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages
.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    'HuggingFaceTB/SmolLM3-3B',
    revision='a07cc9a04f16550a088caea529712d1d335b0ac1',
    local_dir='/mnt/e/DynamisLM-A0/a01/tokenizer', token=False,
    allow_patterns=['tokenizer.json', 'tokenizer_config.json',
                    'special_tokens_map.json', 'chat_template.jinja'],
)
PY
export RES541_A01_TOKENIZER_DIR=/mnt/e/DynamisLM-A0/a01/tokenizer
.venv/bin/python -m pytest -q tests/test_res541_a0.py tests/test_res541_a01.py
.venv/bin/python -m scripts.a01_experiment \
  --tokenizer-dir "$RES541_A01_TOKENIZER_DIR" \
  --baseline-report /mnt/e/DynamisLM-A0/reports/res541-a0-20261023-040456z-report.json \
  --postmortem-dir /mnt/e/DynamisLM-A0/reviews/res541-a0-20261023-040456z-postmortem-v1 \
  --output /mnt/e/DynamisLM-A0/a01/cpu-qualification-HEAD.json
unset PYTHONPATH RES541_A01_TOKENIZER_DIR
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

## Separate measurements for a future approved run

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
