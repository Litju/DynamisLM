# RES-541 A0.1 runtime portability implementation

Proposed activation decision: **KEEP INACTIVE / NO COMPUTE AUTHORIZED**.
Baseline: `e84eed98879a66512d28b90a9f945ac573c0566e`. The historical runtime decision,
failed attempt and A0 source/report bytes remain unchanged.

The executable profile `RES541_A01_CPYTHON313_T4_V1` lives in
`scripts/a01_runtime.py`. It proposes standard final CPython 3.13 patches on Linux
x86-64, standard `cpython-313-x86_64-linux-gnu` ABI, GIL enabled and no debug build.
Torch remains exactly `2.11.0+cu130`, CUDA runtime `13.0`, one `Tesla T4`, SM 7.5,
and FP16. Unknown or missing metadata rejects. The proposed family is a candidate
screen; execution additionally requires a finite reviewed patch allowlist.
Currently that list is empty, activation is false, and both approval records are null.

Activation is a separately reviewed source change: supply independent review and
owner approval records with distinct identities and inspectable evidence, set the
reviewed patch list, and activate. Records are attestations reviewed in the PR,
not cryptographic authentication. Review must qualify the proposed builds/wheel
combination; CPU tests do not establish hardware or numerical equivalence. Refresh
the standalone runtime source SHA-256 in `a01_colab_entry.py` after any adapter or
profile change. Re-run QA and exact-head hosted CI. No approval is supplied here.
The older V1 decision remains a historical proposal, not the active gate.

## Adapter and evidence

Execution binding V2 adds the profile ID/content hash. The uploaded standalone
bootstrap fetches and SHA-checks the runtime adapter from the exact approved
source before executing it. Both frozen A0 modules are SHA-checked. The adapter
compiles only the designated function after finding exactly one original Python
comparison, replacing that comparison with a real-metadata compatibility check.
It changes no interpreter metadata and leaves the Torch, hardware, dependency,
resource, checkpoint and decoding checks in those functions in place. A0's
original files/imported module instances and V1 historical hashes remain intact.

Before setup, source cloning or tokenizer/weight downloads, bootstrap captures
Python implementation, full version, build, compiler, executable, ABI, GIL/debug
flags, OS/architecture; Torch/CUDA; GPU name, count, UUID, capability, VRAM and
nvidia-smi driver metadata. Capture errors remain explicit. The FP16 field is the
required load policy; actual loaded parameter dtype is checked by the frozen loader.
An exclusive-create inventory sidecar is written before qualification. An
incompatible runtime produces a NO_GO report containing that inventory, profile
hash, source and run ID, with no setup or model download. Existing report or
inventory paths are rejected rather than reused. Host raw downloads remain
unaltered and control/verified receipts use exclusive creation.

Preparation transfers the bootstrap inventory into the inference process.
Inference qualifies again before any tokenizer asset download and at the frozen
loader's Python gate before weights. Its inventory must equal bootstrap's except
for the venv executable path. Both observations and their digest accompany model
outputs; every case hash includes that digest. CPU replay requalifies the evidence
and cross-checks the frozen loader's recorded versions/GPU. Different driver,
build, ABI, hardware, profile hash, or unapproved patch fails closed.

## Next supervised session, not launched

After independent profile qualification and explicit activation, the owner may
use the existing E:-configured launcher with `--suite a0_diagnostic --cases 16`.
Runtime-compatible execution rejects the control suite. Interactive confirmation
includes exact source, prompt/manifest, profile hash, quota, T4 and all existing
budgets. Confirmation is checked afresh and the source is checked again before
allocation. The same single session inventories and, only on qualification,
continues directly to the frozen 16-case experiment. No retry, fallback GPU,
training or PSE path is added. Any failure still attempts bounded report download,
stop and explicit zero-session verification; unknown teardown remains an error.

All local QA logs, reports, caches and temporary files use `/mnt/e/DynamisLM-A0`;
remote model caches remain ephemeral. The SmolLM3 revision, frozen A0.1 prompt,
strict parser, RES-69/70 authority, 3.12.13 scientific engine and token/time/weight
budgets are unchanged. A changed Python patch makes any historical comparison
prompt-plus-runtime, with runtime as a confounder. Final adversarial/scientific
review is still required before merge; this PR remains draft.
