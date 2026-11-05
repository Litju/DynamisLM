# RES-541 A0.2

A0.2 is one synthetic, development-only inference run for `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1`. It does not train the model, access PSE material, or qualify formal benchmark performance.

`protocol-v1.json` freezes the model, tokenizer, prompts, decoding limits, case manifests, scoring rules, and source hashes. Its `pre_inference_revision` records the source repair and prior protocol/source hashes. The revision does not change the first 16 A0.1 comparison cases, ten A0.2 cases, gold expectations, model/tokenizer, prompts, or scoring rules. The first 16 cases retain the exact A0.1 case manifest, system prompt, rendered input messages, template date, tokenizer IDs, and decoding settings. The ten new cases are fixed synthetic requests derived from deterministic RES-402 constructors plus two independently authored trust/claim cases. No A0.2 model output informed their authoring.

## Execution path

The historical A0.1 action schema remains unchanged for the paired 16. The new cases use the strict RES-403 action parser. RES-403's closed catalogue is not extended or treated as arbitrary input: the runner binds proposals only to this frozen case manifest, calls typed RES-70 analysis/claim authority, and dispatches the registered RES-69 absolute-change operation only after exact action and request checks. Unsupported causal and composite objectives fail closed; cross-source, incompatible-unit, reliability, association, and missing-evidence cases use their typed refusal path. The fake-result case keeps the forged value in untrusted user content and calculates only from its frozen synthetic observations.

Every case receives two model generations: a typed action, then a short explanation from the trusted executor or application guard event. Raw prompts, token IDs, outputs, app dispositions, engine events, claims, hashes, token counts, and latency are retained separately. WSL CPU replay verifies the downloaded report before producing the scientific metrics. Final grounding checks numeric output and a fixed list of unsupported-claim markers; it does not prove all free-text semantics. Guard rejections remain separate from model understanding.

The science engine runs under Python 3.12.13. Model loading and generation run in a fresh Python 3.13 subprocess using the pinned inference venv ahead of Colab's system site-packages, including the reviewed PyTorch runtime. The runner records each loaded module's version and origin and fails if either differs from the frozen package inventory. `huggingface-hub==0.33.4` receives an explicit asset allowlist; weights are fetched only to the ephemeral Colab VM. `trust_remote_code=False` remains on tokenizer/model loading. The WSL runner strips `PYTHONPATH` and `PYTHONHOME` from every Colab CLI subprocess to keep the A0.1 tokenizer `filelock==3.18.0` environment from conflicting with CLI state.

The runner does not mount Drive in the GPU session. It downloads the report to E:, stops the exact allocated session, verifies the provider reports zero active sessions, and then scores on CPU. A separate connected Google Drive workflow synchronizes the verified evidence package to the owner-only folder and reads each file back to check SHA-256. Drive failure does not trigger another allocation or change the scientific result. The sanitized Colab log omits code, outputs, paths, and credential-like fields.

Final-answer handling is measured only for this fixed synthetic development transcript. It does not qualify arbitrary RES-403 transcript origin or tool-result authenticity beyond these cases.

## WSL commands

The pinned tokenizer and all host artifacts use Windows E: at `/mnt/e/DynamisLM-A0`.

```bash
PYTHONPATH=src:. .venv/bin/python -m scripts.a02_experiment verify
PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages:src:. \
  PYTHONDONTWRITEBYTECODE=1 TMPDIR=/mnt/e/DynamisLM-A0/tmp \
  HF_HOME=/mnt/e/DynamisLM-A0/cache/huggingface \
  USE_TORCH=0 USE_TF=0 USE_FLAX=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  .venv/bin/python -m scripts.a02_preflight
.venv/bin/python -m scripts.a02_execution preflight --attempt 4
.venv/bin/python -m scripts.a02_execution run --attempt 4
```

`run --attempt 4` binds the source revision, protocol/case/prompt hashes, attempt-3 recovery lineage, current Colab balance and rate, active-session inventory, and the 900-second T4 cap. It proceeds only after a fresh exact phrase is typed in an interactive WSL terminal and a second quota/session snapshot still matches. The controller preserves attempts 1–3, writes the separate `attempt-004-used.json` marker, and starts a bounded watchdog before allocation. Teardown verifies the exact target name and endpoint in both the authenticated CLI session list and provider assignments; unrelated sessions remain active and are not treated as the A02 target. Automatic retries and paid upgrades remain disabled.

After CPU scoring, use the connected Google Drive file workflow to upload the small evidence package to the existing owner-only folder. Read each uploaded file back and compare its SHA-256 with `artifact-hashes.json`, recording the file IDs and verification results in a separate local receipt. A Drive failure leaves the E: evidence and scientific result intact; it does not authorize another GPU allocation.

## Attempt 3 bootstrap repair

Attempt 2 (`res541-a02-002-0867ebaed2985601c5902829`) consumed its authorization
at source `b5a64c54383172dea4b6af1d9d4918a10625e8e3`, protocol
`d63dfa3537e2b9e279a0c5733b6e2d510ce5f1c48a48216fd313e91a04cde5bb`.
Its retained report contains zero cases and an implicit `venv`/`ensurepip` failure.
The hash-verified control receipt records successful stop, zero sessions, and a
disarmed watchdog (therefore no separate watchdog cleanup receipt). The recorded
balance was 249.98 CU before and after; later account usage cannot be attributed
to this experiment. CLI history was retrieved independently during this repair.

The owner requested one additional bounded attempt after both infrastructure
failures. Its eligibility is bound to the append-only E: inventory
`attempt-003-recovery-inventory.json`, SHA-256
`9796cccbb6eba3e502ff7d36ebaaab01c9c47225dd5667cf0aea5f56ccc487e2`.
That inventory includes both markers, prior recovery inventory, all attempt-2
artifacts, and the independently retrieved sanitized history. Fresh interactive
confirmation is required; this request does not supply the dynamic confirmation.

Bootstrap checks the actual parent interpreter, creates a venv with
`--without-pip`, checks parent pip's `--python` support, and installs only the
pinned binary `uv==0.12.2` with no dependencies. If parent pip is absent or too
old, it extracts only the executable from the size-bounded, SHA-256-verified
PyPI manylinux x86_64 wheel. No remote installation script is executed.
Interpreter prefix/version, executable access, and uv version are verified.
The scientific engine remains Python 3.12.13 with frozen lockfile sync;
inference inherits Colab's reviewed interpreter/PyTorch and installs the existing
exact pins as wheels without dependency resolution. Full sanitized stderr,
command, exit status (null on timeout/spawn failure), bootstrap stage, runtime
inventory, and free disk space remain in the partial report on failure.

Attempt 3 is consumed and its recovery disposition remains
`A02_ATTEMPT3_EVIDENCE_VALIDATION_FAILED` with no scientific decision. The
retained historical admission adapter is pinned to the original recovery bundle
and rejected `a02-valid-numerical` at frozen prompt admission. The current scorer
uses a later protocol/source binding and cannot be applied directly to that older
report; no attempt-3 score is reconstructed or replaced. The
versioned attempt-4 contract binds all prior markers, both recovery inventories,
and the complete attempt-3 recovery manifest. The protocol revision records old/new
runner hashes and its predecessor protocol hash; case, prompt, model, and decision
bindings remain unchanged. CPU qualification covers bootstrap, evidence lineage,
current quota, exact-target teardown, and the report-to-scorer pipeline. Actual
CUDA/model behavior still requires the fresh owner-authorized T4 execution.

The CPU-only end-to-end rehearsal admitted all 26 prompts, replayed all trusted
executor events, scored all 26 synthetic actions, grounded all final answers, and
persisted both reports. It returned `STAGE_A_SCIENTIFIC_NO_GO` because the frozen
`refuse-practical-meaning` expectation requires
`RES70_COMPARABILITY_AUTHORITY_MISSING`, while exact executor replay emits
`RES70_STATISTICAL_AUTHORITY_INSUFFICIENT` and
`RES70_UNSUPPORTED_CLAIM_ESCALATION` (reason agreement 16/17). The frozen case,
authority output, and threshold were left unchanged. This blocks a Stage A
development-go qualification until the scientific reason contract is reconciled.
