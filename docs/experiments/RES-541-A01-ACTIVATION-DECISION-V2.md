# RES-541 A0.1 runtime activation V2 — development only

Source activation follows [CPU preparation](https://github.com/Litju/DynamisLM/commit/2f28191db3a94321fb0e9b0a4ff9da2aac3cae30).
It does **not** authorize paid Colab allocation, certify live compatibility,
approve a merge, or revise historical A0 scientific results.

## Attributable records

- **Owner:** `Litju`, documented by [agent-relayed direct owner instruction](https://github.com/Litju/DynamisLM/pull/46#issuecomment-6458914435).
  This covers CPU-only activation for four candidate patches and a prospective
  one-T4, 16-case budget; the owner reserves personal exact interactive confirmation
  before allocating compute. Do not portray the relayed GitHub post as a
  personally signed GitHub message.
- **Separate automated reviewer:** `coderabbitai[bot]`, [review #5677323707](https://github.com/Litju/DynamisLM/pull/46#pullrequestreview-5677323707)
  at exact source `2f28191db3a94321fb0e9b0a4ff9da2aac3cae30`. Review
  state is COMMENTED, not APPROVED; it is not a human review.
- **Findings:** The original A0 host accepted `origin` although the Colab
  bootstrap clones `Litju/DynamisLM`. A0.1 now checks the canonical branch's
  exact SHA before allocation and again after interactive confirmation, without
  editing frozen A0. The other finding is a misleading historical A0 CLI
  error prefix. A0.1 has a separate entry and does not print that prefix.

These are inspectable attestations, not cryptographic authentication,
a human scientific signoff, or automatic GPU authorization.

## Conditional compatibility screen

The activated profile `RES541_A01_CPYTHON313_T4_V1` accepts only prospective
Python `3.13.15`, `3.13.16`, `3.13.17`, `3.13.18`, with standard CPython
Linux x86-64 ABI, GIL enabled and non-debug build. Torch must remain exactly
`2.11.0+cu130`, CUDA `13.0`, one T4 SM7.5, and FP16 load policy.
Bootstrap/inference inventory agreement, exact package/model/science/decoder
contracts, 1024/64 token bounds, 8GiB weight ceiling and frozen-source
hashes remain mandatory. Actual Colab compatibility and numerical
equivalence are unproven; the old failed VM's version remains unknown.
The historical A0 source and A0.1 frozen prompt/cases/RES-69/70 remain unchanged.

## Before any Colab execution

After exact-head CI and E:-local tokenizer replay, recheck current quota,
zero active sessions and E: mount; personally enter the exact new
interactive confirmation. Permit only one T4 `a0_diagnostic --cases 16`
with up to 900 seconds of remote run, plus bounded 120s report download,
30s stop and 30s zero-session verification, which can incur extra compute
charges. Inventory the actual VM before weight download. If any gate
rejects, retain evidence and verify teardown. No automatic retry,
second suite, alternative GPU, training, PSE access or merge. A0.1
scientific performance is unmeasured until real model outputs exist.

**Source activation is not live GPU authorization or scientific acceptance.**
