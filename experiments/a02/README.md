# RES-541 A0.2

A0.2 is one synthetic, development-only inference run for `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1`. It does not train the model, access PSE material, or qualify formal benchmark performance.

`protocol-v1.json` freezes the model, tokenizer, prompts, decoding limits, case manifests, scoring rules, and source hashes. Its `pre_inference_revision` records the source repair and prior protocol/source hashes. The revision does not change the first 16 A0.1 comparison cases, ten A0.2 cases, gold expectations, model/tokenizer, prompts, or scoring rules. The first 16 cases retain the exact A0.1 case manifest, system prompt, rendered input messages, template date, tokenizer IDs, and decoding settings. The ten new cases are fixed synthetic requests derived from deterministic RES-402 constructors plus two independently authored trust/claim cases. No A0.2 model output informed their authoring.

## Execution path

The historical A0.1 action schema remains unchanged for the paired 16. The new cases use the strict RES-403 action parser. RES-403's closed catalogue is not extended or treated as arbitrary input: the runner binds proposals only to this frozen case manifest, calls typed RES-70 analysis/claim authority, and dispatches the registered RES-69 absolute-change operation only after exact action and request checks. Unsupported causal and composite objectives fail closed; cross-source, incompatible-unit, reliability, association, and missing-evidence cases use their typed refusal path. The fake-result case keeps the forged value in untrusted user content and calculates only from its frozen synthetic observations.

Every case receives two model generations: a typed action, then a short explanation from the trusted executor or application guard event. Raw prompts, token IDs, outputs, app dispositions, engine events, claims, hashes, token counts, and latency are retained separately. WSL CPU replay verifies the downloaded report before producing the scientific metrics. Final grounding checks numeric output and a fixed list of unsupported-claim markers; it does not prove all free-text semantics. Guard rejections remain separate from model understanding.

The science engine runs under Python 3.12.13. The model runs under the reviewed Python 3.13/T4 compatibility profile with pinned Transformers and tokenizer packages. `huggingface-hub==0.33.4` receives an explicit asset allowlist; weights are fetched only to the ephemeral Colab VM. `trust_remote_code=False` remains on tokenizer/model loading. The WSL runner strips `PYTHONPATH` and `PYTHONHOME` from every Colab CLI subprocess to keep the A0.1 tokenizer `filelock==3.18.0` environment from conflicting with CLI state.

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
.venv/bin/python -m scripts.a02_execution preflight --attempt 2
.venv/bin/python -m scripts.a02_execution run --attempt 2
```

`run --attempt 2` displays the exact source revision, protocol/case/prompt hashes, incident inventory, current Colab balance, one-session T4 limit, 900-second cap, and no-retry/no-upgrade policy. It proceeds only after the owner types the displayed phrase in an interactive WSL terminal. The controller preserves the original `one-attempt-used.json` and forensic inventory, writes an exclusive replacement authorization and `attempt-002-used.json`, and starts a separate bounded watchdog before allocating. The watchdog attempts to stop only this session if the controller dies or its deadline expires. A stop is considered verified only when the provider session listing independently confirms zero active sessions. No third attempt is authorized.

After CPU scoring, use the connected Google Drive file workflow to upload the small evidence package to the existing owner-only folder. Read each uploaded file back and compare its SHA-256 with `artifact-hashes.json`, recording the file IDs and verification results in a separate local receipt. A Drive failure leaves the E: evidence and scientific result intact; it does not authorize another GPU allocation.
