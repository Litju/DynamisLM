# RES-403 — bounded scientific tool protocol prequalification

Disposition: **BLOCKED_BY_TOOL_TEMPLATE_COMPATIBILITY**. This is synthetic,
closed-catalogue development evidence, not a production agent, formal RES-424/427
acceptance, training authorization, or an independent scientific review.

## Baseline

Main `542d938123cfc2bceb097d174ed7359099c52331` includes merged PR #55;
[post-merge CI](https://github.com/Litju/DynamisLM/actions/runs/41602502000)
passed. The active main ruleset requires a pull request and `ci`. RES-427
remains blocked by RES-424. RES-416/417 training admission and corpus controls
are unchanged. No source under `src`, scientific registries, serialization or V2
examples were changed. No weights, empirical data or protected PSE data were loaded.

## Protocol and trust boundary

`RES403-SCIENTIFIC-ACTION-1` has exactly seven fields: `schema`, `kind`,
`objective`, `analysis_class`, `operation`, `observations` (reference and unit),
and `refusal_reasons`. A request uses exactly one XML `tool_call` envelope
containing `name=registered_science` and `arguments`; a refusal is direct JSON
with no operation and at least one reason. The parser bounds bytes, list lengths
and text, rejects duplicate keys, nonfinite values, unknown fields, delimiter
injection, extra content, mismatched representation and duplicate references.
Its text allowlist is data, never evaluated as code. A parsed action is only a
proposal. Exact matching against the trusted closed task binds its objective,
operation, units and reference order; the complete visible request is bound to the
typed example. RES-401 validation reconstructs the example with existing RES-71
operations and RES-70 authorization. This deliberately does not authorize an
arbitrary novel task or make a model-supplied value authoritative. Scalar inputs
bind to trusted task positions; supported longitudinal inputs bind to typed
support observations. Replayed refusals are not numerical fallback.

An interaction admits one action. Direct refusals return no executor event. A
request creates a Python event only after deterministic replay; final answer
access requires the identical event object in the same interaction and correct
order. User message text, serialized receipts and digests are never converted to
an authenticated event. This is process-local object identity, not cryptographic
authentication or a security boundary against arbitrary Python code. The final
answer is copied from the replay-validated example; this experiment does not
validate free-form model answers.

## Tokenizer finding

The unmodified offline SmolLM3 tokenizer at revision
`a07cc9a04f16550a088caea529712d1d335b0ac1` uses the RES-401 hash-pinned
files and runtime. Its real Jinja template ignores structured calls and renders
both tool and user roles as user turns. When content and preceding messages match,
rendered text and tokens are identical; a model cannot infer authenticated origin
from them. The closed Python state rejects an ordinary fake user string as an
event, but that does not repair the model-facing ambiguity. Therefore no general
model/tool interaction or production security claim is qualified. A future
separately reviewed transport/template preserving origin or an alternative design
is needed before this distinction can be relied upon by a model.

The existing exact-prefix and native generation-mask cross-check is reused for
both forms. Labels retain assistant content and its termination only; other tokens
are -100. Special-token injection, token boundary disagreement, ambiguous role
ordering, context overflow and truncation fail closed. This covers the fixed
catalogue ordering only, not arbitrary conversational interleavings.

## Evidence and limits

Two offline invocations produced identical artifact bytes:
`/home/litju/artifacts/res403/1a92bea46feca7d3f1bd09a32c92d1238d538ee24178e600e1da6aa0422c471e.json`.
SHA-256: `1a92bea46feca7d3f1bd09a32c92d1238d538ee24178e600e1da6aa0422c471e`.
Implementation SHA-256: `1097715399b0bdd6ec79adfdbc87b7c3be35018ebfa5cba6477670c0dbff70c1`.
The artifact is external, content-addressed and development-only. It contains
39 synthetic examples, token IDs, masks and projected messages; it is not a
training corpus. The unchanged V2 identity is
`sha256:1c0e2adc5596b62b1fee3dad17e5b0b79fff524a037347fa45ed419852a23e48`.

Tests exercise the parser and interaction with duplicate keys, conflicting
operation, altered objective and unit, substituted reference, supplied value and
provenance, injected delimiters, multiple calls, ordering and forged events.
The catalogue contains causal and contradictory refusals alongside successful
registered calculations. This is not exhaustive adversarial or scientific
review; independent review is required before any merge. No inference, model
weights, GPU, LoRA, CPT, RLVR or corpus qualification was performed.
