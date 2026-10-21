# RES-541 — WSL → official Colab CLI → remote GPU (development-only)

Authority: [RES-541](https://linear.app/alignerr-cmj/issue/RES-541/a0-wslcolab-gpu-scientific-reasoning-alpha-development-only). This is a **Research Alpha A0** preflight and experiment, **not** RES-420 qualified M0 and not PSE V1. Work only on the dedicated RES-541 branch, never the PSE or RES-407 worktrees.

## Architecture
VS Code Remote–WSL + Codex edit/test the Ubuntu repo. Google **official** Colab CLI runs local scripts on **hosted Colab** compute. CLI supports Linux; WSL is Linux. No Docker, browser notebook upload or unsupported remote tunnel is needed.

## Local WSL setup (no GPU allocated)
```bash
cd ~/projects/DynamisLM-RES541
uv tool install google-colab-cli
colab version
colab --auth=oauth2 sessions
colab --auth=oauth2 usage
```

If the CLI asks for Google OAuth permission, the **owner** completes the browser consent/code entry interactively. Never copy authentication codes, session tokens, OAuth configuration or `~/.config/colab-cli` into PRs, chats or agent transcripts. If `colab` is not on `PATH`, check `uv tool dir --bin` and `uv tool update-shell`. The CLI does **not** mean Colab is running on WSL hardware.

No Colab GPU is guaranteed by this setup; hardware availability and costs depend on the connected Google account.

## Explicit owner-authorized remote hardware preflight

After the owner sees the quota/usage and approves starting a session:

```bash
colab --auth=oauth2 run --gpu T4 scripts/a0_colab_preflight.py
colab --auth=oauth2 sessions
```

`colab run` provisions a transient **remote** GPU runtime, transfers the local Python script, runs it, and normally releases the runtime on exit. Check `sessions` afterward and stop any remaining session explicitly. The script does not load/download model weights. It prints actual CUDA availability, GPU identity/VRAM, Python/Torch version and free remote disk. It returns a nonzero exit code when CUDA is absent or reported GPU memory is below the screening threshold. A successful preflight **does not** guarantee model runtime fit.

If T4 is unavailable, out of quota, or incurs unexpected compute fees, **stop and ask the owner**; don't silently provision A100/L4/H100, retry endlessly, or change runtime tiers.

## Reproducible A0 execution

The implementation is `scripts/a0_colab.py`, `scripts/a0_colab_entry.py`, `scripts/a0_colab_inference.py`, and `scripts/a0_engine.py`; fixed cases and inference pins live under `experiments/a0/`. `colab run` transfers only the entry script. The entry script therefore clones and verifies the full repository at the exact pushed Git SHA before it imports or executes scientific code.

From WSL, after CPU QA and pushing the clean RES-541 branch revision:

```bash
uv run --frozen --python 3.12 scripts/a0_colab.py run --output-dir reports/a0
```

The local wrapper checks that the checkout is clean, on the issue's mission branch, and pushed at the exact `HEAD`. It runs `colab --auth=oauth2 usage`, refuses active assignments, displays the available quota, and requires the owner to enter an exact confirmation string before provisioning. It requests one T4 runtime with a 900-second CLI timeout. There is no retry or tier fallback. OAuth prompts remain interactive and must be completed by the owner; no authentication state or tokens are copied to the repository.

The remote entry point fails closed unless it sees Python `3.13.15`, PyTorch `2.11.0+cu130`, one T4, compute capability 7.5, at least 12 GiB total and 8 GiB free VRAM, and 12 GiB free disk. It clones the full public repository, checks out the exact SHA in a clean detached worktree, and provisions Python `3.12.13` with `uv==0.12.2` and `uv sync --frozen`. That isolated Python 3.12 environment runs the RES-62/69/70 builders and authorities. The Python 3.13 inference venv uses `--system-site-packages` to inherit Colab's existing PyTorch and installs only the exact inference requirements with `--no-deps`; it verifies the imported PyTorch version and file path still match the base Colab runtime.

Before fetching weights, inference reads pinned Hugging Face Safetensors metadata and refuses a checkpoint larger than 8 GiB or inadequate free disk. It loads `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1` with `trust_remote_code=False`, Safetensors, and FP16 on the T4. Generation is greedy (`do_sample=False`, one beam), seeded with `541`, and bounded to 1,024 prompt tokens and 64 new tokens for each of the 16 fixed cases. The source cases contain only newly authored synthetic development values and independent expected outcomes; there is no PSE, RES-407, hidden split, or real athlete data.

The model emits only a typed intent. Python resolves its baseline/follow-up roles to exact canonical entry IDs, authorizes the RES-70 `SCALAR_ABSOLUTE_CHANGE` capability, calls the registered RES-69 `follow-up - baseline` operation, validates the exact result, and asks RES-70 claim authority to permit the numerical-change claim. Model output cannot contain a numeric result or executable code. Missing support, unequal units/metrics, cross-athlete support, unregistered operations, causal claims, and practical-meaning claims are refusal cases.

The small JSON report includes the source SHA, model and dependency revisions, GPU/precision/config, prompt and generation token counts, first-token and total latency, peak VRAM/RAM, disk/weight bytes, per-case intents/results/refusals, denominators, and failure categories. It reports `PASS`, `PASS_WITH_LIMITATIONS`, or `NO_GO`; the 16-case development suite has no confidence limits or generalization claim. The remote experiment deadline is 840 seconds, leaving margin inside the Colab 900-second timeout. `--keep` allows the local wrapper to download the report, stop the session, and verify it is absent from active sessions. Reports are written to `reports/a0/`; no weights, caches, credentials, or large data are retrieved.

Run inference only after the owner confirms the current quota and this bounded execution budget. No training, fine-tuning, HF upload, formal M0/PSE qualification, or merge is authorized. Keep this work on draft PR #46 for independent scientific review.

Official docs:
- [Google Colab CLI](https://github.com/googlecolab/google-colab-cli)
- [Google Colab VS Code extension](https://marketplace.visualstudio.com/items?itemName=Google.colab)
- [VS Code WSL guide](https://code.visualstudio.com/docs/remote/wsl)
- [SmolLM3-3B pinned model card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/tree/a07cc9a04f16550a088caea529712d1d335b0ac1)
- [Transformers 4.53.0 SmolLM3 documentation](https://huggingface.co/docs/transformers/v4.53.0/en/model_doc/smollm3)
