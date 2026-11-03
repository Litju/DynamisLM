# RES-541 A0.2

A0.2 is one synthetic, development-only inference run for `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1`. It does not train the model, access PSE material, or qualify formal benchmark performance.

`protocol-v1.json` freezes the model, tokenizer, prompts, decoding limits, case manifests, scoring rules, and source hashes. The first 16 cases retain the exact A0.1 case manifest, system prompt, rendered input messages, template date, tokenizer IDs, and decoding settings. The ten new cases are fixed synthetic requests derived from deterministic RES-402 constructors plus two independently authored trust/claim cases. No A0.2 model output informed their authoring.

## Execution path

The historical A0.1 action schema remains unchanged for the paired 16. The new cases use the strict RES-403 action parser. RES-403's closed catalogue is not extended or treated as arbitrary input: the runner binds proposals only to this frozen case manifest, calls typed RES-70 analysis/claim authority, and dispatches the registered RES-69 absolute-change operation only after exact action and request checks. Unsupported causal and composite objectives fail closed; cross-source, incompatible-unit, reliability, association, and missing-evidence cases use their typed refusal path. The fake-result case keeps the forged value in untrusted user content and calculates only from its frozen synthetic observations.

Every case receives two model generations: a typed action, then a short explanation from the trusted executor or application guard event. Raw prompts, token IDs, outputs, app dispositions, engine events, claims, hashes, token counts, and latency are retained separately. WSL CPU replay verifies the downloaded report before producing the scientific metrics. Final grounding checks numeric output and a fixed list of unsupported-claim markers; it does not prove all free-text semantics. Guard rejections remain separate from model understanding.

The science engine runs under Python 3.12.13 (`pyproject.toml` remains unchanged). The model runs under the reviewed Python 3.13/T4 compatibility profile with pinned Transformers and tokenizer packages. Weights are fetched only to the ephemeral Colab VM. The WSL runner strips `PYTHONPATH` and `PYTHONHOME` from every Colab CLI subprocess to keep the A0.1 tokenizer `filelock==3.18.0` environment from conflicting with CLI state.

## WSL commands

The pinned tokenizer and all host artifacts use Windows E: at `/mnt/e/DynamisLM-A0`.

```bash
PYTHONPATH=src:. .venv/bin/python -m scripts.a02_experiment verify
PYTHONPATH=/mnt/e/DynamisLM-A0/a01/tokenizer-venv/lib/python3.12/site-packages:src:. \
  PYTHONDONTWRITEBYTECODE=1 TMPDIR=/mnt/e/DynamisLM-A0/tmp \
  HF_HOME=/mnt/e/DynamisLM-A0/cache/huggingface \
  USE_TORCH=0 USE_TF=0 USE_FLAX=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  .venv/bin/python -m scripts.a02_preflight
.venv/bin/python -m scripts.a02_execution preflight
.venv/bin/python -m scripts.a02_execution run
```

`run` displays the exact source revision, current Colab balance, one-session T4 limit, 900-second cap, and no-retry/no-upgrade policy. It proceeds only after the owner types the displayed phrase in the interactive WSL terminal. The runner downloads only the small report to E:, stops the session even on failure, verifies zero active sessions, and runs `scripts.a02_score` on WSL CPU. It never downloads model weights to the host.

The first confirmed allocation attempt creates `one-attempt-used.json` on E:. Every later preflight refuses to launch another GPU attempt, including after an unsuccessful allocation.
