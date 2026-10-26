# RES-541 A0.1 runtime decision V1

Disposition: **BLOCKED_RUNTIME_VERSION_UNKNOWN**. Reviewed source:
`f62347234954b0ca994bfbb2046b8972aa251cbd`. The accompanying
[machine-readable decision](../../experiments/a01/runtime-decision-v1.json) is
inactive and unapproved. It changes no production gate and authorizes no compute.

## Recovered evidence

The failed A0.1 attempt used source
`37db8457271ec89691da07daaf2c3b4d73f5b1ac`, run
`res541-a01-a0-diagnostic-20261025-093109735899`. Its observed Python, Torch and CUDA
versions are **UNKNOWN**. The report's `runtime_preflight` is empty. Torch imported
before the Python gate failed, but that does not establish its version. The
retained CLI history has one execution stream containing the mismatch category
and a SystemExit(1), with no runtime-version observation. Version literals in
uploaded code, synthetic tests and release notes are not measurements of this VM.

The following original files were read without modification:

| E:-local evidence | SHA-256 |
| --- | --- |
| `a01/runtime-failure-review-f623472.json` | `c2d53649767fc37b0cbb14bd32010efb05f34062f399f3eaf1222e677b341b0f` |
| `reports/a01/diagnostic/res541-a01-a0-diagnostic-20261025-093109735899-remote.json` | `875f8a45633524355133015f86b1f76b31ca8b7a598b4822ba3fb87c36951feb` |
| `reports/a01/diagnostic/res541-a01-a0-diagnostic-20261025-093109735899-control.json` | `f72cc537b344c306ad93633d127319759ebf2a2d5868967d3b8e435d6e62ed7a` |

Paths are relative to `/mnt/e/DynamisLM-A0/`. The nonsecret CLI-history audit is
`a01/runtime-decision-history-audit.json`; credentials and raw history are not
copied into Git. The original history SHA-256 is
`1c1833a2897019822c80242ea1b1f1e90e39a3c4894e90a634ec93a2ef28036f`.
The control receipt records successful stop and zero sessions; these are historical
observations, not a new live account check.

## Actual selection controls

[Colab's runtime-version FAQ](https://research.google.com/colaboratory/runtime-version-faq.html)
documents a past-image dropdown in **Runtime → Change runtime type**. It does not
document selecting arbitrary Python patch versions. The listed images describe
those images, not this failed VM; no observed version is inferred from that list.

The tagged v0.7.5 [run command](https://github.com/googlecolab/google-colab-cli/blob/v0.7.5/src/colab_cli/commands/run.py)
accepts session, GPU/TPU, high-memory, keep, timeout and environment options.
[Session selection](https://github.com/googlecolab/google-colab-cli/blob/v0.7.5/src/colab_cli/commands/session.py)
resolves hardware/shape. The [client assignment interface](https://github.com/googlecolab/google-colab-cli/blob/v0.7.5/src/colab_cli/client.py)
accepts notebook hash, variant, accelerator and shape. There is no runtime-image
or interpreter-version parameter in this inspected CLI path. `--env` changes
remote process variables, not the kernel binary. No undocumented API, interpreter
installation, CLI launch, or image-selection workaround was attempted.

## Candidate, not an approved compatibility claim

[CPython 3.13's ABI documentation](https://docs.python.org/3.13/c-api/stable.html)
supports same-minor binary compatibility when builds are compatible. It also
warns that private APIs and interpreter behavior can change. This supports
evaluating standard CPython 3.13 final patch releases, not declaring arbitrary
builds, Torch wheels or numerical results interchangeable.

The JSON candidate screen requires CPython 3.13 final releases, the standard
Linux x86-64 CPython 3.13 ABI, GIL enabled, no debug build, exact Torch
`2.11.0+cu130`, reported `torch.version.cuda == "13.0"`, one Tesla T4 with capability
7.5, and FP16. All fields must be observed; UNKNOWN fails closed. Passing this
screen is necessary to consider a patch-only proposal and never sufficient to
authorize a launch. The approved patch allowlist remains empty because the failed
runtime and its builds could not be established. Different Python minors,
prereleases, free-threaded/debug builds, Torch versions or CUDA runtimes require
separate scope; they are not patch-only compatibility.

The model/tokenizer revision, prompt and case hashes, package pins, source Python
3.12.13 authority, greedy non-thinking decoding, seed, token/weight/time budgets,
VRAM/disk thresholds, canonical registries, owner approval, CLI isolation, E: host
storage and remote-only weights remain governed by the unchanged frozen execution
contract. The candidate does not replace any of those checks.

## Both gates and future enforcement

Both `scripts/a0_colab_entry.py::_preflight` and
`scripts/a0_colab_inference.py::run_inference` currently require Python 3.13.15 and
Torch 2.11.0+cu130 exactly. The existing A0.1 wrappers still invoke those gates.
Changing only the bootstrap would leave inference blocked. Neither gate currently
expresses a CPython-build compatibility profile; this decision does not pretend
that it already does. CPU tests inspect both gates without changing their source
or overriding `platform.python_version()`.

After explicit recorded approval, a separate implementation would bind the
approved profile ID, content hash and finite approved patches into the source,
preparation, model output and replay receipts. Both A0.1 checkpoints must validate
real implementation/version/build metadata, Torch/CUDA, hardware and existing
limits with the same profile before any model download. The inference process
must agree with the bootstrap inventory. Missing or conflicting evidence rejects.
This requires a new execution-binding version; the existing V1 binding and
historical hashes cannot be silently broadened.

An implementation route preserving A0 bytes is a reviewed AST transformation of
the two SHA-verified **private module instances** already used by the adapters:
replace only each exact Python comparison with the approved profile check, after
asserting the expected function and comparison occur exactly once. The original
Torch/hardware/dependency/download gates remain. Any source/AST drift rejects.
The shared check reads actual runtime metadata; it must never alter `platform`,
`sys.version`, Torch versions or returned observations to satisfy old checks.
This transformation is a future reviewed change, not implemented or activated
here. An independently implemented A0.1 gate/loop is an alternative requiring
review of all preserved validation; neither approach is justified as a quick
exception handler around a failed frozen gate.

## Historical comparison boundary and unblock evidence

The immutable historical A0 report, SHA-256
`d0881e600cc7b729c894122db504f596dab60a270814ff47796a662e87482303`, actually records
Python 3.13.15, Torch 2.11.0+cu130, CUDA 13.0, Tesla T4 and FP16. Those measurements
must not be assigned to A0.1. A future different patch would make the experiment
a prompt-plus-runtime comparison, with runtime as a confounder, not a prompt-only
causal comparison. Actual full versions/builds and the approved profile must be
reported alongside each result; identical numerical/model output is not promised.

Unblocking needs genuine Python implementation/version/build and Torch/CUDA
inventory for an eligible runtime, compatibility qualification, a recorded
profile/patch approval, both adapter gates and replay binding implemented and
reviewed together, and fresh owner authorization. None of the missing inventory
can be supplied by release notes. No compute is allocated to obtain it in this
mission; historical A0 and failed A0.1 evidence remain immutable.
