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

## Model execution (future Codex work on this branch; NOT implemented by preflight)
- Pinned post-trained `HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1` as *inference-only* candidate.
- Explicitly pin model/runtime dependencies and revision, and verify usable dtype for actual device (T4 FP16, not blindly BF16).
- Stage a source package from the same repository Git SHA onto the VM; don't assume `colab exec -f local.py` transfers Python imports or the whole repository.
- Run fixed, **newly authored synthetic development** cases only; call the existing registered within-athlete scalar absolute change analysis through validated canonical Python contracts, never eval/exec raw LM code.
- Add fail-closed refusal cases and typed result validation; avoid PSE candidate material, hidden splits, restricted data and existing test-case leakage.
- Bound cases, prompt/output tokens, memory, runtime, and remote artifact sizes. Download sanitized run receipts and logs; do not commit secrets, checkpoints, model cache or large generated datasets.
- Human account approval for GPU/session/weights is required. No inference, training or fine-tuning is authorized outside RES-541's exact development-only scope.
- Finish with ordinary hosted CI, independent scientific review and **one** mission PR against `main`. No merge without review.

Official docs:
- [Google Colab CLI](https://github.com/googlecolab/google-colab-cli)
- [Google Colab VS Code extension](https://marketplace.visualstudio.com/items?itemName=Google.colab)
- [VS Code WSL guide](https://code.visualstudio.com/docs/remote/wsl)
