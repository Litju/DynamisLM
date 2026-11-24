# Frozen step-510 PEFT adapter bundle

Build from the four original RES-541 adapter files in the authorized local evidence directory. Use a
trusted checkout containing the RES-772 verifier, with the repository's Python environment already
provisioned. Both commands work offline and use CPU file operations.

```bash
umask 077
evidence="$HOME/.local/share/dynamislm-evidence"
adapter="$evidence/RES-746-qualification.BKKAML/t4-final/staging/adapter"
snapshot="$evidence/RES-746-real-model.fOXGaI/snapshot"
output="$evidence/RES-772-adapter-bundle"
mkdir -p "$output"

uv run --offline --no-sync python -m scripts.alpha_adapter_bundle build \
  --adapter-dir "$adapter" --archive "$output/first.tar"
uv run --offline --no-sync python -m scripts.alpha_adapter_bundle build \
  --adapter-dir "$adapter" --archive "$output/second.tar"
cmp "$output/first.tar" "$output/second.tar"
uv run --offline --no-sync python -m scripts.alpha_adapter_bundle verify \
  --archive "$output/first.tar" --base-dir "$snapshot"
```

Omit `--base-dir` to verify the archive and its base reference without a local snapshot.
With `--base-dir`, the verifier also hashes all nine registered base and tokenizer files in that
directory. The base reference is
`HuggingFaceTB/SmolLM3-3B@a07cc9a04f16550a088caea529712d1d335b0ac1`.
The build refuses to overwrite an existing archive. The verifier prints the archive and member
digests as JSON. It checks the tar without extracting it.

| Archive member | Contents |
| --- | --- |
| `adapter/adapter_model.safetensors` | Original frozen LoRA weights, byte-identical |
| `adapter/adapter_config.json` | Portable PEFT config with the base ID and exact revision |
| `provenance/metadata.json` | Original training checkpoint metadata, byte-identical |
| `provenance/evaluation-binding.json` | Original A0.2 evaluation binding, byte-identical |
| `MANIFEST.json` | `DYNAMISLM_ADAPTER_BUNDLE_V1` identity, lineage, runtime and distribution state |
| `SHA256SUMS` | SHA-256 for every other member |
| `LICENSE` | Pending-decision placeholder by default |
| `NOTICE` | Upstream attribution and distribution scope |

The uncompressed USTAR archive uses lexically sorted regular members, mode `0644`, timestamp zero
and UID/GID zero. The manifest includes the source and release config digests. The verifier
reconstructs the original PEFT JSON from the release form and compares it with the original pinned
digest. It checks the remaining frozen files directly and regenerates the registered manifest from
trusted checkout pins and verified payload bytes.

## Licensing and evidence scope

RES-771 D2 governs adapter licensing. The current verifier reports
`distribution: LICENSE_DECISION_REQUIRED` and `publication_qualified: false`, even when structural
integrity passes. Use `verify --require-publication` to make that status a nonzero exit. A missing
`LICENSE` entry is a structural error. Use `build --license-file PATH` to include supplied license
text verbatim and `verify --license-file PATH` with the trusted original text to check its identity.
Supplied text leaves the publication gate closed pending the owner's decision and a release
authorization. The repository source-code license is separate from the adapter license decision.

The bundle establishes the identity of a frozen adapter, its referenced base, and recorded
development lineage. It includes no base weights or tokenizer assets. A0.2's recorded decision is
`ESCALATE_TO_STRONGER_MODEL_COMPARISON`. D0 and the RES-746 CPU and T4 results are development
evidence. Scientific validation, runtime execution, legal approval, and publication authorization
are outside this verification.
