# RES-401 — CPU tokenizer and model-facing supervision development qualification

This is a closed 39-example development experiment, not RES-424 acceptance or a
RES-427 production runtime. No inference, model weights, training, GPU, empirical
athlete data, protected PSE data, rights grants or exclusion commitments are used.
Independent tokenizer/supervision review and owner authorization remain required
before merge. Scientific validation is not self-certified by this report.

## Baseline and isolation

Canonical checkout: `/home/litju/projects/DynamisLM`.
Base: `54493e25942bbed9eef1192c6c0c9ee01e95d680`, PR #54 merged.
Post-merge [CI 41182969347](https://github.com/Litju/DynamisLM/actions/runs/41182969347)
completed successfully. Linear RES-401 is the mission; no new issue was created.
RES-418/420/424/427 were inspected and remain Backlog with their existing gates.

A new script, its isolated dependency lock, tests and this report are added,
with the two required non-code inventory entries under the unchanged policy.
The implementation deliberately lives outside `src/dynamislm`: V2's implementation
identity hashes every Python file there. Moving this script there would change
V2 artefact identities. No V2 code, scientific engine, registry, serialization,
production loader or root export is edited.

The unchanged V2 SHA-256 is
`1c0e2adc5596b62b1fee3dad17e5b0b79fff524a037347fa45ed419852a23e48`.
Its original CPU receipt remains
`97f649cbb249a832df1d6a990a5594136c1d04fc38f5217c3b70658e42f945b9`.
A regression test reconstructs and checks the complete V2 bytes against that
pre-edit identity, rather than changing an expected hash to accommodate edits.

## Runtime and tokenizer identities

Model/tokenizer: `HuggingFaceTB/SmolLM3-3B`, revision
`a07cc9a04f16550a088caea529712d1d335b0ac1`.
The existing local snapshot is
`/home/litju/.cache/huggingface/hub/models--HuggingFaceTB--SmolLM3-3B/snapshots/a07cc9a04f16550a088caea529712d1d335b0ac1`.
All four symlink targets were independently hashed and checked against existing
`TOKENIZER_PINS`; no tokenizer resource or model weight was downloaded.

| File | SHA-256 |
| --- | --- |
| tokenizer.json | `7b6a500b662a34eb3f0374db856ba4ad7de4c81040571d78dc0d357238930005` |
| tokenizer_config.json | `59a64b39f05ee0acf7479bbccf99a44d9e481c1a4a494eb03838ae3c35eb29be` |
| chat_template.jinja | `3e0e275a527f249670056e0078e474eadbdd007c134b4fdfae5a7b3089702814` |
| special_tokens_map.json | `12403efb970f069ba62ddf3b66166a27254be4a198166b61ad1ee604bd3a4515` |

Python 3.12.13; Transformers 4.57.1; Tokenizers 0.22.1; Jinja2 3.1.6.
The actual implementation is `PreTrainedTokenizerFast`. Every transitive tokenizer
runtime dependency is version/hash pinned in `scripts/res401-runtime.lock`; this
adds no dependency to the scientific core. The user explicitly approved this
isolated runtime download. A broken uv cache entry required a `--no-cache` retry
of the same hash-locked packages. No torch/TensorFlow/Flax runtime is installed
in that environment. Existing project dependencies/test tools are exposed through
its existing site-packages for catalogue replay and tests. The core retains its
existing uv.lock; all visible package versions are recorded in the receipt.

`AutoTokenizer.from_pretrained` uses `local_files_only=True` and
`trust_remote_code=False`. Runs set `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. The loaded template must exactly equal the pinned Jinja
file. The receipt preserves the loaded template, tokenizer configuration and
special-token configuration.

## Actual template findings and bounded remedy

The unmodified V2 conversations are executed twice through the actual template.
The template reads assistant `content` but ignores `tool_calls` completely: all
30 structured calls disappear. Tool messages render as `user`, without tool-call
IDs or names. Without system override/tools, its default system header also lacks
a closing `im_end` before the first user turn and injects the current date.
Consequently V2 JSON validity does not establish chat compatibility. The receipt
records every legacy token count/hash, rendered-text hash and delimiter counts.
Legacy hashes include the execution day's default metadata and are not claimed
to reproduce across dates.

The new projection uses the template's existing `/system_override /no_think`
branch with fixed scientific instructions, action-field documentation and the
four existing registered-operation candidates. This closes the system header and
removes wall-clock metadata without editing or replacing the template. Tool calls
are XML-wrapped JSON in assistant **content**, matching the format the actual
SmolLM3 template describes. Executor tool results are represented in the existing
`tool` role and render as user turns. Exact role ordering and delimiter counts
are verified. This supports the closed catalogue only; authenticated production
tool-result channels and arbitrary user/tool interleavings remain RES-427 work.

## Projection and executor contract

`RES401-MODEL-PROJECTION-1` and
`RES401-TOKENIZER-SUPERVISION-RECEIPT-1` are independently versioned.
The frozen `ScientificAction` contains schema, request/refuse kind, objective,
requested RES-70 analysis class or null, candidate registered operation or null,
visible `{reference, unit}` observation selections and local refusal reasons.
Requested class/operation are proposals, never authorization assertions.

Observation references are request-visible `observation-N` aliases scoped to the
trusted example. External bindings point to complete typed trusted observations
where supplied, or to the original task's scalar-input positions. Source/method,
measurement identity, time, units and missing/comparability evidence remain in
the visible evidence request. Category, seed/index, gold outcomes, receipts and
internal support/request/provenance hashes stay outside model messages.

`execute_proposal` rejects extra dict fields, altered objectives, operations,
references, units or request bytes. An accepted proposal triggers exact V2
scientific reconstruction/validation, using the existing RES-71 operation adapters
and canonical RES-70 authorization path. It returns only the replay-validated
engine response. The model supplies neither authoritative numbers nor hashes.
This exact-catalogue equality boundary intentionally does not parse arbitrary
natural language or implement a production agent.

`projection[*].messages` is the sole model input/target surface. `action` is the
typed semantic target serialized as a dict. Sibling `example_sha256` and
`executor_bindings`, and bundle `external_ground_truth`, are external audit data,
not model inputs. Full V2 arguments, result hashes, refusals, support, methods and
provenance remain in `external_ground_truth`. No executor hash appears in an
assistant message, including final explanations. Final numerical text is copied
only from the original replay-validated answer after the authoritative tool result.

## Exact assistant-only labels

The actual template contains Jinja `generation` blocks. Its native assistant
mask includes assistant role headers, fixed no-thinking preamble and trailing
newline. We independently derive exact token prefixes for each assistant turn:
completed preceding messages, the actual generation prompt, and the completed
assistant message. Each must be an exact prefix of the full token sequence;
any boundary merge fails closed. Decoding the proposed content span must equal
the exact assistant content. There is no substring search for assistant text.

The complete native mask must equal the independently derived assistant-turn
ranges. Labels retain only assistant content plus its single `im_end` token;
role headers, thinking scaffold, separator newline, system/user/tool material
are `-100`. No padding is constructed (the configured pad token equals EOS, so
future padding must be masked by position, not by token identity). Truncation is
disabled. The conservative native model limit is 65,536, not the tokenizer's
131,072 advertised maximum. Unavailable masks, disagreement, invalid roles,
reserved delimiter injection, overflows or non-round-tripping spans fail closed.

## Reproduction

Use the existing checkout and exact local snapshot, never weights. Installing the
locked runtime requires explicit package-download authorization; the run itself
is offline. The project environment is provisioned by `uv sync --frozen`.

```sh
uv venv --python 3.12 /external/res401-runtime
uv pip sync --python /external/res401-runtime/bin/python --require-hashes scripts/res401-runtime.lock
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
PYTHONPATH=src:.venv/lib/python3.12/site-packages \
/external/res401-runtime/bin/python scripts/res401_supervision.py \
  --tokenizer-directory /external/exact-pinned-snapshot \
  --output-root /external/res401-artifacts
```

Repeat the command and compare the content-addressed JSON bytes. Each command
also independently reloads the tokenizer twice and compares every token ID,
label, span, legacy rendering identity and diagnostic. Receipts include the
script and runtime-lock identities. Artifacts remain external, private and
content addressed; V2 outputs are never overwritten.

```sh
uv sync --frozen
uv run pytest tests/test_res401_supervision.py tests/test_res402_sft.py -q
uv run pytest -q
./scripts/ci.sh
# Actual tokenizer tests, in the isolated runtime:
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
RES401_TOKENIZER_DIRECTORY=/external/exact-pinned-snapshot \
PYTHONPATH=src:.venv/lib/python3.12/site-packages \
/external/res401-runtime/bin/python -m pytest tests/test_res401_supervision.py -q
```

Standard CI deliberately skips the one real-runtime test when the explicitly
selected external snapshot/runtime is absent. That skip is never tokenizer
qualification evidence; the separate real-runtime run is required.

## Production denial and remaining gates

Every bundle explicitly states `DEVELOPMENT_ONLY`, `BATCH_LOCAL_ONLY`,
`TRAINING_AUTHORIZED = false`, `CORPUS_QUALIFIED = false`, and
`MODEL_WEIGHTS_UPDATED = false`. Forged, rehashed or reloaded receipts cannot
pass the unchanged production corpus loader. RES-416/417 source rights,
contamination/exclusion screening and global corpus/split assembly remain
mandatory. RES-418 freeze, RES-424 formal dataset acceptance, RES-427 runtime,
RES-420 untouched M0 and frozen PSE/evaluation prerequisites remain unsatisfied.
Any future inference, SFT or GPU run needs its own explicit authorization and
run binding. No optimizer or model weight was loaded or updated here.

## Measured execution evidence

External content-addressed bundle: `/home/litju/artifacts/res401/qualification/40f4e3e11202f11e0d96f4c44a8ca21a9f79ab3fa411d1c6c82e57b9ec1bde21.json`.
Bundle SHA-256: `40f4e3e11202f11e0d96f4c44a8ca21a9f79ab3fa411d1c6c82e57b9ec1bde21`.
Two independent tokenizer reloads match every ID, label and span.

- projection_sha256: `sha256:a31beed5ffba0427b7cff0cdad527561391edbb341838aa86fbf2945b60c2385`
- token_replay_sha256: `sha256:da0bab51165a6b4c1d2c80e363d0dc1354239704c4f0017be0bd4fa09f01cb38`
- legacy_replay_sha256: `sha256:35903fba10b8ae76c6d9aab3f8ccb9cf18190691831e8f81bab889c2f805f8ef`
- runtime_lock_sha256: `sha256:d7c88297482aac7e768a6ddb3be0b1399ecce8aaa5ebbf1f754f97b93f0a7242`
- implementation_sha256: `sha256:f7d0ee7997acb7d38c709d08a5466a7cc65ad3360e5040640752b40382336abe`

Projected lengths (min/median/P95 nearest-rank/max): **683 / 814 / 908 / 908**.
Unmodified V2 lengths: **480 / 605 / 721 / 724**.
Both sets have zero overflow and no truncation. The new projection contains
31,196 total tokens: 5,829 supervised and 25,367 ignored across 69 assistant turns.

The replay records 39 rejections each for incorrect operation, method, missing
evidence, model-provided number/hash, objective downgrade, unsupported comparison,
wrong observation and wrong unit; three forged/rehashed/replayed corpus receipts
are rejected by the unchanged loader. These checks are deterministic adversarial
regressions, not independent scientific acceptance.

| Task index (external only) | Category (external only) | V2 tokens | Projection tokens | Supervised tokens |
| --- | --- | ---: | ---: | ---: |
| 0 | UNIT_CONVERSION | 559 | 683 | 126 |
| 1 | DURATION_RATE | 613 | 767 | 141 |
| 2 | LONGITUDINAL | 666 | 811 | 149 |
| 3 | METHOD_SELECTION | 669 | 817 | 151 |
| 4 | DESCRIPTIVE_DISPERSION | 721 | 908 | 160 |
| 5 | UNIT_MISMATCH | 626 | 839 | 165 |
| 6 | RELIABILITY | 603 | 819 | 146 |
| 7 | CROSS_SOURCE | 627 | 842 | 160 |
| 8 | MISSING_DATA | 545 | 728 | 130 |
| 9 | UNKNOWN_PROVENANCE | 480 | 770 | 155 |
| 10 | CAUSAL | 501 | 792 | 157 |
| 11 | CONTRADICTORY | 507 | 797 | 160 |
| 12 | NO_DOWNGRADE | 596 | 814 | 143 |
| 13 | UNIT_CONVERSION | 561 | 683 | 126 |
| 14 | DURATION_RATE | 612 | 767 | 141 |
| 15 | LONGITUDINAL | 669 | 816 | 149 |
| 16 | METHOD_SELECTION | 672 | 822 | 151 |
| 17 | DESCRIPTIVE_DISPERSION | 717 | 908 | 160 |
| 18 | UNIT_MISMATCH | 622 | 839 | 165 |
| 19 | RELIABILITY | 605 | 819 | 146 |
| 20 | CROSS_SOURCE | 630 | 842 | 160 |
| 21 | MISSING_DATA | 545 | 728 | 130 |
| 22 | UNKNOWN_PROVENANCE | 480 | 770 | 155 |
| 23 | CAUSAL | 501 | 792 | 157 |
| 24 | CONTRADICTORY | 507 | 797 | 160 |
| 25 | NO_DOWNGRADE | 603 | 814 | 143 |
| 26 | UNIT_CONVERSION | 557 | 683 | 126 |
| 27 | DURATION_RATE | 612 | 767 | 141 |
| 28 | LONGITUDINAL | 672 | 821 | 149 |
| 29 | METHOD_SELECTION | 674 | 827 | 151 |
| 30 | DESCRIPTIVE_DISPERSION | 724 | 908 | 160 |
| 31 | UNIT_MISMATCH | 629 | 839 | 165 |
| 32 | RELIABILITY | 607 | 819 | 146 |
| 33 | CROSS_SOURCE | 629 | 842 | 160 |
| 34 | MISSING_DATA | 550 | 733 | 130 |
| 35 | UNKNOWN_PROVENANCE | 480 | 770 | 155 |
| 36 | CAUSAL | 501 | 792 | 157 |
| 37 | CONTRADICTORY | 507 | 797 | 160 |
| 38 | NO_DOWNGRADE | 602 | 814 | 143 |

The second complete process run also blocked `socket.connect`, `connect_ex` and
`create_connection` before importing Transformers. It produced the exact same
bundle and byte-identical summary as the ordinary offline run. The network-denial
log is `/home/litju/artifacts/res401/offline-network-denial.txt`.

The retained catalogue still contains 15 numerical successes, 24 refusals and
30 tool traces across all 13 scientific development categories. Full source and
project-lock diffs against the required base are empty.

The isolated real-tokenizer test run passed all **16 tests**. Full repository QA
and exact-head hosted CI are recorded in the mission PR; the external execution
logs remain under `/home/litju/artifacts/res401/`.
