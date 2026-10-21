# RES-419 — Base model and tokenizer selection

**Date:** 2026-10-20<br>
**Linear:** [RES-419](https://linear.app/alignerr-cmj/issue/RES-419/p7-r1-base-model-and-tokenizer-selection-decision-record)<br>
**Review integration base:** `main` at `74c9e3d05f2da41facc25b7aa0e880d5668cc055` (RES-71 scientific engine gate)<br>
**Historical PSE execution authority baseline:** `5b493be3cc72c3c688c0815e3c97e156fb4ad230` (separate, NOT included in this branch)<br>
**Probe artifact:** [`res419_tokenizer_probe.json`](../../reports/model_selection/res419_tokenizer_probe.json)

## Decision

Select **`HuggingFaceTB/SmolLM3-3B` at `a07cc9a04f16550a088caea529712d1d335b0ac1` as the first CPU-only research candidate**. This is a screening decision for subsequent authorized evaluation, not approval to integrate, serve, or train a model.

The nine probe categories total 559 tokens for SmolLM3 and Granite, 563 for Qwen3-4B, and 571 for Qwen3.5-4B. The original five-category subtotals remain historical screening evidence; the additional four inputs are now included in this result. These small differences are diagnostic only. SmolLM3 ties Granite on the combined count and has the lowest BF16 weight floor at 5.73 GiB, compared with 7.49 GiB for Qwen3, 8.68 GiB for Qwen3.5, and 12.92 GiB for Granite. It has a conventional decoder-only Transformer, a declared 65,536-token context, and documented tool-calling support through Transformers. That is the strongest CPU-oriented starting point among these candidates on the evidence examined.

The choice does not claim scientific reasoning quality, reliable tool execution, safe refusal, or suitability for a production host. Those properties were not tested in this mission.

**Checkpoint role:** This is a provisional choice of an **instruction/reasoning-post-trained model for a future separately authorized inference smoke test**. It is **not** selection of a continued-pretraining (CPT) initialization checkpoint. `HuggingFaceTB/SmolLM3-3B-Base` exists as a distinct base-model lineage and must be compared with the post-trained checkpoint under the future RES-423 training objective, after training/data/GPU gates. Neither weights nor that base model were examined here. Tokenizer overhead cannot establish scientific accuracy or tool-call reliability.

## Rejected alternatives

- **Qwen3-4B:** costs about 1.76 GiB more at BF16 and has a shorter native context. Its lower counts for SI units and the synthetic schema are small tokenizer differences, not evidence of more reliable scientific tool calls.
- **Qwen3.5-4B:** costs about 2.95 GiB more at BF16 and adds vision and hybrid linear/full-attention architecture. Its long native context and newer serving stack add no demonstrated benefit to this CPU tokenizer screen.
- **Granite-4.0-H-Tiny:** ties SmolLM3's aggregate token count, but its total expert weights need a 12.92 GiB BF16 floor despite 1B active parameters. The hybrid MoE/Mamba2 runtime is also more complex for this CPU-first starting point.

## Candidate comparison

| Candidate and immutable revision | License and access | Architecture and stored parameters | Context in the pinned card/config | BF16 weight floor | Documented tooling |
|---|---|---|---|---:|---|
| [Qwen/Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B/tree/1cfa9a7208912126459214e8b04321603b3df60c)<br>`1cfa9a7208912126459214e8b04321603b3df60c` | Apache-2.0; public, not gated; repository includes `LICENSE` | Dense causal Transformer; 4,022,468,096 BF16 parameters; 36 layers, 32 Q / 8 KV heads | 32,768 native; config allocates 40,960 positions; YaRN extension documented to 131,072 | 8,044,936,192 bytes (7.49 GiB) | Transformers `AutoModelForCausalLM`; Qwen-Agent documented for tool calls; vLLM and SGLang examples |
| [HuggingFaceTB/SmolLM3-3B](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/tree/a07cc9a04f16550a088caea529712d1d335b0ac1)<br>`a07cc9a04f16550a088caea529712d1d335b0ac1` | Apache-2.0 declared in the pinned model card; public, not gated; no separate `LICENSE` file in this snapshot | Dense decoder-only Transformer; 3,075,098,624 BF16 parameters; 36 full-attention layers, 16 Q / 4 KV heads | 65,536 trained/configured; YaRN extension documented to 128K and 256K | 6,150,197,248 bytes (5.73 GiB) | Model code documented in Transformers 4.53.0; tool calling documented with XML-wrapped JSON or Python-tool formats; vLLM/SGLang examples |
| [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B/tree/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a)<br>`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | Apache-2.0; public, not gated; repository includes `LICENSE` | Causal LM with vision encoder; hybrid linear/Gated DeltaNet and full-attention layers; 32 text layers; 4,659,861,248 BF16 plus 3,840 F32 stored parameters (the card labels the language model 4B) | 262,144 native; extension to 1,010,000 documented | 9,319,737,856 bytes (8.68 GiB) | Transformers `AutoProcessor` / `AutoModelForMultimodalLM`; model card calls for latest/main SGLang or vLLM for serving and documents tool-call parsers |
| [ibm-granite/granite-4.0-h-tiny](https://huggingface.co/ibm-granite/granite-4.0-h-tiny/tree/791e0d3d28c86e106c9b6e0b4cecdee0375b6124)<br>`791e0d3d28c86e106c9b6e0b4cecdee0375b6124` | Apache-2.0 declared in the pinned model card; public, not gated; no separate `LICENSE` file in this snapshot | Decoder-only hybrid MoE with GQA and Mamba2; 4 attention + 36 Mamba2 layers; 6,939,037,248 BF16 parameters total, with 1B active parameters declared by IBM | 128K declared; config has 131,072 positions | 13,878,074,496 bytes (12.92 GiB) | Transformers `GraniteMoeHybridForCausalLM`; model card documents OpenAI-style function schemas and tool-call tags |

The BF16 floors use the pinned Hugging Face Safetensors parameter metadata and count every stored parameter: two bytes per BF16 element and four bytes per F32 element. They exclude the OS, tokenizer/runtime, activations, KV or recurrent state, allocator overhead, and any load-time copies. They are lower bounds, not measured host RAM requirements. Granite's 1B active-parameter figure describes per-token activation; it does not reduce the amount of unquantized expert weights that must be resident unless a runtime uses an additional memory-saving strategy.

The context comparison uses the model card's native/trained context and the pinned `config.json`. Tokenizer `model_max_length` is not treated as the model context limit: Qwen3's tokenizer value is 131,072 despite its 32,768 native limit, SmolLM3's is 131,072 despite its 65,536 configured limit, and Granite's is a sentinel value. Extensions are reported separately and were not exercised.

## CPU tokenizer probes

[`scripts/res419_tokenizer_probe.py`](../../scripts/res419_tokenizer_probe.py) downloads only each pinned `tokenizer.json`, checks its SHA-256, and tokenizes nine fixed UTF-8 inputs with `tokenizers==0.22.1` and `add_special_tokens=False`:

1. Football performance terminology.
2. Biomechanics.
3. SI units.
4. Scientific notation.
5. A synthetic JSON analysis-tool schema.
6. First-team football microcycle context.
7. Within-athlete measurement uncertainty and causal-language limits.
8. Scientific refusal codes and missing-evidence language.
9. A synthetic typed scientific-refusal output schema.

The schemas are **synthetic tokenizer fixtures**, not live model- or scientific-tool contracts. The extended CPU-only probe additionally includes football microcycle language, within-athlete measurement uncertainty, explicit scientific refusal language, and a typed refusal-output schema. All report scores must be regenerated from exact pinned tokenizer files; do not invent counts from the earlier five-input report. The probe does not apply chat templates or call model code. It records input and token-ID digests so a repeat run can be compared mechanically. Native maximum context and KV-cache behavior remain documentary-only and cannot be inferred from short tokenization fixtures.

| Candidate | Football | Biomechanics | SI units | Scientific notation | Tool schema | Total |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-4B | 50 | 46 | 44 | 56 | 106 | 302 |
| SmolLM3-3B | 46 | 46 | 48 | 51 | 108 | 299 |
| Qwen3.5-4B | 50 | 46 | 48 | 58 | 108 | 310 |
| Granite-4.0-H-Tiny | 46 | 46 | 48 | 51 | 108 | 299 |

The four added categories and nine-input totals are reconciled below. The original five-input subtotal table above retains the first PR's comparison.

| Candidate | Original five | Microcycle | Uncertainty | Refusal text | Refusal schema | Nine total |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-4B | 302 | 52 | 56 | 50 | 103 | **563** |
| SmolLM3-3B | 299 | 52 | 55 | 50 | 103 | **559** |
| Qwen3.5-4B | 310 | 52 | 56 | 50 | 103 | **571** |
| Granite-4.0-H-Tiny | 299 | 52 | 55 | 50 | 103 | **559** |

Pinned tokenizer file SHA-256 values and all nine probe digests are in the regenerated JSON. **Report SHA-256: `65006bdf088e63d4416c8c4ca190282e3a159667edea0396200f10afe0f31ef0`**, independently reconstructed and checked against the [temporary CPU-only GitHub Actions reproduction](https://github.com/Litju/DynamisLM/actions/runs/39517102841). The original five-input report at `sha256:2136f2668761dbc0c3580d3283066ab26890191999b88dd70a091fe3d85820da` remains in PR #44 as historical evidence. Exact repeatability of this nine-input fixture set still requires a second independent nine-input run; only one hosted nine-input run has been completed so far.

### Reproduction

From the repository root with Python 3.12 and `uv`:

```bash
uv run --no-project --python 3.12 --with tokenizers==0.22.1 \
  python scripts/res419_tokenizer_probe.py \
  --output reports/model_selection/res419_tokenizer_probe.json
sha256sum reports/model_selection/res419_tokenizer_probe.json
```

This downloads only `tokenizer.json` files, each pinned by commit and checksum. It does not download model weights or load models.

## Evidence sources

Each link below addresses the immutable snapshot used above. Repository metadata reports `license=apache-2.0` and `gated=false` for all four snapshots. Qwen3 and Qwen3.5 include standalone Apache license text; SmolLM3 and Granite declare Apache-2.0 in their model cards and link to the license text.

| Candidate | Model card and license evidence | Pinned config and tokenizer | Pinned API metadata |
|---|---|---|---|
| Qwen3-4B | [README/model card](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/README.md), [LICENSE](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/LICENSE) | [config.json](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/config.json), [tokenizer.json](https://huggingface.co/Qwen/Qwen3-4B/blob/1cfa9a7208912126459214e8b04321603b3df60c/tokenizer.json) | [revision API](https://huggingface.co/api/models/Qwen/Qwen3-4B/revision/1cfa9a7208912126459214e8b04321603b3df60c?blobs=true) |
| SmolLM3-3B | [README/model card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/blob/a07cc9a04f16550a088caea529712d1d335b0ac1/README.md), [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | [config.json](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/blob/a07cc9a04f16550a088caea529712d1d335b0ac1/config.json), [tokenizer.json](https://huggingface.co/HuggingFaceTB/SmolLM3-3B/blob/a07cc9a04f16550a088caea529712d1d335b0ac1/tokenizer.json) | [revision API](https://huggingface.co/api/models/HuggingFaceTB/SmolLM3-3B/revision/a07cc9a04f16550a088caea529712d1d335b0ac1?blobs=true) |
| Qwen3.5-4B | [README/model card](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/README.md), [LICENSE](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/LICENSE) | [config.json](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/config.json), [tokenizer.json](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/tokenizer.json) | [revision API](https://huggingface.co/api/models/Qwen/Qwen3.5-4B/revision/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a?blobs=true) |
| Granite-4.0-H-Tiny | [README/model card](https://huggingface.co/ibm-granite/granite-4.0-h-tiny/blob/791e0d3d28c86e106c9b6e0b4cecdee0375b6124/README.md), [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | [config.json](https://huggingface.co/ibm-granite/granite-4.0-h-tiny/blob/791e0d3d28c86e106c9b6e0b4cecdee0375b6124/config.json), [tokenizer.json](https://huggingface.co/ibm-granite/granite-4.0-h-tiny/blob/791e0d3d28c86e106c9b6e0b4cecdee0375b6124/tokenizer.json) | [revision API](https://huggingface.co/api/models/ibm-granite/granite-4.0-h-tiny/revision/791e0d3d28c86e106c9b6e0b4cecdee0375b6124?blobs=true) |

SHA-256 of the pinned README files, in candidate-table order: Qwen3 `71add1cd091c309b1cb1a6b943f2476eb2b004124b3bd1d32dcd0b24cc1abc47`, SmolLM3 `24f16f90b883af3618425a589783a944356a7fc2e3cfa69b579c9ff06963e178`, Qwen3.5 `1406be1b6b8fd8a6545870da516912804756593628a1d0fb0a7965211e82a7bb`, Granite `9a2b7bc35ca60174c314e16e61260214f329eaf2372dccdc27814fe719990d95`. Qwen3's standalone license file SHA-256 is `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e`; Qwen3.5's is `bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a`.

## Scientific limits and remaining gates

- Token counts measure segmentation only. They do not measure terminology understanding, unit correctness, scientific reasoning, tool-call validity, refusal, or output quality.
- Model-card tool support is documentary evidence, not a result from this probe. Structured generation and schema adherence remain untested.
- The declared context lengths and memory floors were read or calculated from pinned upstream metadata; no context stress, weight load, CPU inference, or RAM measurement was run.
- Upstream Apache-2.0 declarations, standalone license files, and model-card license links were checked; no separate legal review was performed. Training-data provenance, pretraining contamination, and third-party data rights were not independently audited. No protected PSE split artifacts were queried or used.
- The selected candidate is not computational or scientific authority. DynamisLM's registered deterministic Python operations and claim/measurement authority remain unchanged.
- Before any operational inference or training, require its own explicit authorization and evaluation protocol. This PR is for review only and must not be merged without review.
