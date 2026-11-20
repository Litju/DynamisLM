# DynamisLM synthetic research CLI

The RES-747 candidate is an offline CPU demonstration on Linux x86-64 with CPython 3.12. It packages the existing A0.3 action grammar and RES-70 admission together with a deterministic RES-69 synthetic example. The package is a pre-release candidate. Use a dedicated virtual environment for this distribution, which bundles the shared DynamisLM scientific modules.

## Build and install

Use uv and Python 3.12 in the source checkout. Build from the committed source. Use a new output directory each time.

```sh
uv run --frozen python -m scripts.build_research_cli /tmp/dynamislm-cli-candidate
uv run --frozen python -m scripts.verify_research_cli /tmp/dynamislm-cli-candidate

uv venv --python 3.12 /tmp/dynamislm-cli-demo
uv pip install --python /tmp/dynamislm-cli-demo/bin/python /tmp/dynamislm-cli-candidate/*.whl
/tmp/dynamislm-cli-demo/bin/dynamislm-research demo absolute-change
```

The example uses two synthetic readings of 0.25 m and 0.375 m in the same qualified synthetic scope. It emits the visible request, scripted V3 proposal, admission and claim-decision fields, and the registered result of **+0.125 m**. The canonical result hash binds the complete result. The installed command uses no network or model dependencies for these examples.

## Inspect and exercise refusal

With the demonstration environment's `bin` directory on your path, run the following commands.

```sh
dynamislm-research --version
dynamislm-research identity
dynamislm-research demo missing-evidence
dynamislm-research demo unsupported-operation
dynamislm-research demo causal-escalation
dynamislm-research demo practical-escalation
```

A grounded example exits with status 0. A refusal emits a JSON receipt with reasons and a null result, exits with status 2, and performs no scientific operation. The association example uses a recognized analysis with unavailable computation. The causal and practical examples submit syntactically valid escalations to the existing authorization boundary. The demonstration only accepts the named built-in cases.

The identity command shows the exact source commit and tree and the hash of the canonical included-file digest manifest. The build receipt separately records the SHA-256 of the wheel file. The clean-install receipt captures the installed version, reproducible numerical output, four refusals and exact wheel identity.

## Model-backed research path

The CPU candidate produces a scripted proposal. The separately qualified source-based A0.3 inference path uses the C1 prefix mask and requires a qualified NVIDIA Tesla T4 with at least 14 GiB free before load, matching Colab CUDA 13.0 and CPython 3.13, PyTorch 2.14.1+cu130, Transformers 4.53.0, tokenizers 0.21.1, and PEFT 0.16.0. It binds SmolLM3-3B revision `a07cc9a04f16550a088caea529712d1d335b0ac1`, the four pinned tokenizer files and the frozen step-510 LoRA adapter. Adapter weights SHA-256 is `7bda8c60c2e27206d60a41f7f454ecce721e46704e731b4f6c268d042572a6e7`. Consult the associated source-bound runtime manifest for the complete bindings. The consumed D0 authorization is historical. Any prospective paid inference requires its own exact-source approval.

## License and release scope

The candidate contains AGPL-3.0-only source, license and notice, and relies on the existing original synthetic source builder for the fixtures. External dependencies are version-pinned and installed independently. No model weights, adapter, tokenizer assets, benchmark data, empirical rows, or protected evidence are included. Model and adapter distribution rights require separate checks against the exact proposed artifact. The prospective RES-746 scientific result and final exact-release review set the scope for a model-backed publication. A failed or inconclusive gate retains the scoped report-only decision unless a separate owner-approved deterministic-only scope is established. This is research software for synthetic examples.
