# DynamisLM model-backed research CLI

This alpha runs one C1 scientific-action proposal over packaged synthetic scenarios. The
deterministic RES-70 admission path can authorize RES-69 signed absolute change (later minus
earlier), or return a refusal or abstention. The installation contains the scientific kernel and
model runtime code. Model assets stay in separate local directories.

## Install and stage assets

Use Linux x86_64 and CPython 3.13. The qualified profile uses torch 2.14.1+cpu, FP32 and MATH SDPA.
Allow at least 16 GB RAM. The previous RES-746 CPU qualification peaked at about 15.0 GB RSS and
generation took minutes per question. The installed runtime retains greedy C1 decoding, the
SmolLM3 chat template, and the qualified no-autocast, no-TF32 settings.

Build from a clean committed checkout and install outside the checkout. The constraint file pins
the CPU dependencies. Prepare or cache these wheels before taking the installation offline.

```bash
python3.13 -m scripts.build_research_cli /path/to/wheel-dir
uv venv --python 3.13 /path/to/research-env
python=/path/to/research-env/bin/python
uv pip install --python "$python" --index https://download.pytorch.org/whl/cpu \
  --no-deps 'torch==2.14.1+cpu'
uv pip install --python "$python" --constraint packaging/research-model-constraints.txt \
  '/path/to/wheel-dir/dynamislm_research-0.1.0a2-py3-none-any.whl[model]'
```

For a CUDA qualification setup, select `torch==2.14.1+cu130` from
`https://download.pytorch.org/whl/cu130` and install its CUDA dependencies from the wheel metadata.
Use the same pinned model extra and the registered [A0.3 T4 setup](../../experiments/a03/runner.md).
RES-746 recorded 13.43 GB peak CUDA reserved and about nine seconds per call on T4. RES-430's
installed runtime is qualified only on CPU. `ask --device cuda` exits 4 pending separate installed
CUDA qualification.

Obtain the authorized exact snapshot of
`HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1` out of band. Stage real
regular copies of the nine files listed in the RES-772 manifest into a dedicated read-only
directory with no cache metadata, snapshots, symlinks or extra files. Put the original RES-772 tar
in a directory by itself, or pass its file path. The archive and snapshot should remain stable
through the entire command. Inference uses local-only model loading and offline Hub flags.

The bundle passes structural verification for authorized internal use.
`LICENSE_DECISION_REQUIRED` blocks public distribution pending RES-771 D2.

## Run

```bash
cli=/path/to/research-env/bin/dynamislm-research
"$cli" verify-base --base /path/to/snapshot
"$cli" ask --scenario absolute-change \
  --question 'What is the absolute change between these two synthetic readings?' \
  --bundle /path/to/bundle --base /path/to/snapshot --device cpu > result.json
```

The example returns the registered calculation of 0.125 m. JSON goes to stdout and fixed-template
text to stderr. The receipt preserves the original question, C1 proposal bytes and token IDs,
admission status, claim ceiling, and evidence, model and execution identities.

| Scenario | Synthetic evidence |
| --- | --- |
| `absolute-change` | Comparable readings from one athlete |
| `unit-incompatibility` | Different units with no authorized conversion for this calculation |
| `protocol-incompatibility` | Different acquisition protocols |
| `cross-source-incompatibility` | Distinct sources and unbridged processing methods |
| `missing-evidence` | Two readings with no trusted record binding |
| `single-observation` | One authentic synthetic reading with insufficient support for change |

Exit codes are 0 for a grounded calculation, 2 for refusal or abstention, 3 for artifact or input
integrity failure, and 4 for an unsupported runtime. The CLI accepts question text and catalogue
IDs. The library's `scripts.research_scenarios.SyntheticScenario` and `validate_scenario`, and
`scripts.research_ask.ask`, also support authored synthetic evaluation scenarios. They take no
evaluation gold or adjudicator input.

A calculation is grounded for the admitted proposal. The model can misread causal or
practical-meaning questions and silently propose a simpler numerical task. RES-70 checks the
proposal and evidence and cannot independently detect every mistranslation of the original
question. The receipt presents the original wording beside the proposal and labels the result as a
calculation for that proposal. Generalization and public release require separate qualification.
