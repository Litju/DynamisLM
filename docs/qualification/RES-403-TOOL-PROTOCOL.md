# RES-403 — trusted transcript adapter qualification

Disposition: **READY_FOR_INDEPENDENT_ORIGIN_ADAPTER_REVIEW**. This CPU-only
qualification covers a closed synthetic catalogue, application-controlled event
origin, model-visible encoding with the pinned tokenizer, and deterministic token
masks. It does not qualify model behavior, prompt-injection resistance, a generic
science agent, production security, training, or RES-427.

## Mission and preserved authority

The work continues on `work/res-403-tool-protocol` and draft PR #56. The reviewed
starting head was `8a76862746a8ab16f50775decbcd1c442b71f39b`; base `main` remains
`542d938123cfc2bceb097d174ed7359099c52331`. The active repository ruleset
requires a pull request and strict `ci` status. No scientific registry, RES-70/71
authority, V2 examples, Serialization V3 code, empirical data, or model-training
authority changed. The V2 identity remains
`sha256:1c0e2adc5596b62b1fee3dad17e5b0b79fff524a037347fa45ed419852a23e48`.
RES-424/427 and RES-416/417 remain unchanged.

### Historical compatibility NO-GO

The original failed proof remains valid for the unmodified SmolLM3 template and
unwrapped messages: native `tool` and `user` turns with identical content and
preceding messages render to identical text and token IDs. That finding is
retained as the historical baseline; the pinned Jinja template was not changed.
Its original artifact remains
`/home/litju/artifacts/res403/1a92bea46feca7d3f1bd09a32c92d1238d538ee24178e600e1da6aa0422c471e.json`
(SHA-256
`1a92bea46feca7d3f1bd09a32c92d1238d538ee24178e600e1da6aa0422c471e`).

## Adapter and runtime boundary

`RES403-MODEL-TRANSCRIPT-1` uses frozen, explicit event types for system
instructions, untrusted user input, model action proposals, direct model
refusals, trusted executor results, and model final answers. The renderer maps
them to deterministic chat messages. System instructions remain in the system
role with their leading SmolLM3 controls intact. Other payloads use canonical,
compact ASCII JSON envelopes with distinct origin values; `<` and `>` are escaped
before template rendering. Payload decoding rejects malformed, duplicate-field,
unknown-schema, oversized, and noncanonical envelopes and round-trips the exact
original Unicode code points without normalization.

The pinned template still maps a native `tool` role to a user turn. The adapter
therefore renders an executor result as a `tool` message with an
`origin=trusted_executor_result` envelope, while ordinary user content receives
an `origin=untrusted_user_input` envelope. Copying the complete visible executor
envelope into a user message nests it as escaped user payload and keeps the event
untrusted. Origin strings are serialization labels only; neither the renderer nor
the parser treats a marker or model output as executor authorization.

Only `Interaction` creates a `TrustedExecutorResultEvent`, after the existing
closed-catalogue proposal match and deterministic replay. Its public constructor
rejects calls. The runtime retains the event object, per-interaction call
identity, sequence, and issuer outside the language-model transcript. The final
answer stage requires that same event object, call identity, and order. No public
API accepts a user-selected trust flag or converts user text into an executor
event. This is an application API boundary, not a sandbox against arbitrary code
running inside the Python process. No cryptographic key or authentication secret
is included in prompts.

`Interaction.submit_action` decodes only a model action/refusal envelope, checks
that its event kind matches the parsed action, then reuses the existing strict
RES-403 parser, closed-catalogue binding, and RES-401/RES-70/71 deterministic
validation. Invented operations, units, observations, missing evidence,
unsupported comparisons, causal/contradictory downgrades, model-proposed values,
and model-proposed provenance hashes remain nonauthoritative or rejected.

## Pinned-tokenizer evidence

Qualification used only the cached offline tokenizer for
`HuggingFaceTB/SmolLM3-3B`, revision
`a07cc9a04f16550a088caea529712d1d335b0ac1`, with the original four SHA-256 pins:

| File | SHA-256 |
| --- | --- |
| `tokenizer.json` | `7b6a500b662a34eb3f0374db856ba4ad7de4c81040571d78dc0d357238930005` |
| `tokenizer_config.json` | `59a64b39f05ee0acf7479bbccf99a44d9e481c1a4a494eb03838ae3c35eb29be` |
| `chat_template.jinja` | `3e0e275a527f249670056e0078e474eadbdd007c134b4fdfae5a7b3089702814` |
| `special_tokens_map.json` | `12403efb970f069ba62ddf3b66166a27254be4a198166b61ad1ee604bd3a4515` |

The isolated offline runtime remained `transformers==4.57.1`,
`tokenizers==0.22.1`, and `jinja2==3.1.6`; the unchanged runtime-lock SHA-256 is
`d7c88297482aac7e768a6ddb3be0b1399ecce8aaa5ebbf1f754f97b93f0a7242`.

The new paired proof uses the same executor payload and byte-identical preceding
messages. Under the actual Jinja template, the genuine executor event and the
same-payload user event produce different visible messages and different token
sequences; the preceding token prefix is identical. Their token lengths in the
recorded witness are 846 and 847. A user message containing the entire visible
executor-result envelope remains user-originated and produces a third token
sequence (881 tokens). The ordinary unwrapped tool/user equality proof above
continues to pass as historical evidence.

## Token masks

All 39 synthetic examples were rendered through the adapter and rechecked with
the pinned tokenizer. The artifact contains 34,415 input tokens, 7,590 supervised
tokens, and 26,825 `-100` ignored tokens across 69 assistant turns: 30 explicit
scientific action targets, 9 direct refusal targets, and 30 final-answer targets.
Executor, user, and system messages receive no assistant labels. Native Jinja
assistant masks match independent exact token-prefix alignment. Assistant
content and turn endings are retained; the actual template path disables
truncation and rejects context overflow above 65,536 tokens. Each individual
event payload is bounded to 8,192 UTF-8 bytes.

The action and refusal strings remain parser-compatible after envelope decoding.
The final-answer target is copied from the replay-validated synthetic example;
free-form model answers remain unqualified.

## Adversarial qualification

Tests cover special-token and XML injection, JSON escaping, exact NFC/NFD
preservation, nested payloads, delimiter collisions, malformed JSON, duplicate
fields, noncanonical envelopes, the 8,192-byte boundary, literal copying of the
full visible executor envelope, direct raw-action submission, unissued event
construction, cross-call event substitution, replay, and out-of-order final
answers. Existing scientific adversarial replay rejects each of these 39 times:
incorrect operation, wrong observation, wrong unit, objective downgrade, method
mutation, missing evidence, unsupported comparison, and model-supplied number or
hash. Three forged/rehashed/replayed corpus receipts remain denied. Causal and
contradictory requests still cannot be downgraded to a calculation.

These are deterministic code and tokenizer checks. No inference was run, so they
do not establish that a language model will obey, understand, or resist attacks
against these origin labels.

## Deterministic external evidence

Two independent offline invocations produced byte-identical content-addressed
artifact bytes:

- Artifact: `/home/litju/artifacts/res403/d268e3cf022f4f17752a0734506ab9c8a570dfff20af36db41954b97a51966cb.json`
- SHA-256: `d268e3cf022f4f17752a0734506ab9c8a570dfff20af36db41954b97a51966cb`
- Both run-log output SHA-256 values: `d9e301a2c0067e9717a543a539ffbd3b8511858c976f74295ec31af3418e7c7e`
- Adapter implementation SHA-256: `2a454d3443110ac01da1758ccfd2a0ffbadf80cdd77c99ae23bf0b008d0c30bf`

The artifact is outside Git, synthetic, development-only, and not a training
corpus. No model weights, inference, optimizer, SFT, LoRA, CPT, RLVR, GPU,
empirical athlete data, or protected PSE data were used. The result is ready for
independent origin-adapter review; exact-head hosted CI remains independent merge
evidence, and this PR remains draft and unmerged.
