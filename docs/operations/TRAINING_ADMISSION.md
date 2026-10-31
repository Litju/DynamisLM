# RES-416 training-source admission

This boundary prepares data loading; it does not authorize training runs. PSE V1
remains SCIENTIFIC_NO_GO. The four RES-63 empirical audit decisions are unchanged.

## Trust installation

`registries/training_authority.json` is read from the exact Git HEAD, never from
working-tree edits or applicant metadata. It initially contains no grants.
Production release uses the repository containing the installed module and an
independently provisioned SHA-256 commitment embedded in the reviewed code release.
The commitment currently pins the empty registry. Neither a different Git HEAD,
a matching remote URL, environment configuration nor caller metadata can install
new production authority. Any registry change (including revocation) fails closed
until a separately reviewed code release provisions its exact new commitment.
Install this code through a trusted release process; an attacker who can replace
the installed Python code is outside this boundary's trust model. There is no
production trust/clock override; tests inject their authority only via monkeypatch.

A grant is exact UTF-8 JSON with schema `RES416-GRANT-1`; see the isolated
synthetic fixture in `tests/test_res416_admission.py` for every required field.
It binds source identity, version, SHA-256 bytes, source class, license, explicit
weight-training use, CPT/SFT purposes, transformations, attribution, validity,
partition, excluded material, and upstream content digests. Supply all upstream
inputs, including engine output inputs and benchmark-derived material. No grant
can permit validation material through the TRAIN partition.

Before installing a pin, an independent reviewer must verify the owner's actual
rights and delegation, license scope, commercial restrictions, transformations,
attribution, provenance, and exact-content contamination clearance. Text requires
independent text rights; original instructions require authorship evidence; engine
traces require existing qualified deterministic operations and their provenance;
empirical data requires separate explicit training rights and preserved population
and qualification restrictions. Engine output does not create input data rights.
The admission mechanism does not replace scientific or population qualification.

A pin contains `grant_sha256`, `authority`, `rights_evidence`,
`independent_review`, and `contamination_review` references. These are public,
non-secret review references. The exact grant digest is the mechanically verified
allowlist; these references are not signatures and the software does not infer
legal authority from their wording. Install pins only through an independently
reviewed mission PR. Do not install test identities in the production registry.
Keep owner documents, source bytes and keys outside Git. Review references must
resolve to independently retained evidence before installation. Revocation adds
the exact grant digest to `revoked`; changed rights require a new grant digest.
Populate `protected_digests` with known protected inputs. Digest matching detects
exact contamination; paraphrase and partial overlap require the independent
content review pinned with the grant. No heuristic detector claims scientific
clearance. Unknown provenance must never receive a pin.

## API and CLI

`admit_sources` is a historical diagnostic, never a production permission gate.
Its caller-selected repository and timestamp can produce a positive audit for an
untrusted repository; such an audit confers no authority. It takes tuples of `(Request, exact_content_bytes, exact_grant_bytes)`,
a repository root and explicit timezone-aware evaluation time. It returns a
reproducible content-addressed manifest containing AUTHORIZED, DENIED or
EVIDENCE_REQUIRED decisions, purpose, restrictions and exact grant/source digests.
It does not emit source content or evidence documents. Keep grant attribution
metadata public and free of athlete data, answers and secrets.

Run `uv run python -m dynamislm.training_data REQUEST.json --repository-root REPO
--evaluated-at 2026-10-30T00:00:00+00:00`. REQUEST.json is a list with `source`
(the Source fields), `purpose`, `transformations`, `content_path`, `grant_path`,
and optional `partition` (TRAIN). Content and grant paths must be outside REPO.
Stdout is the manifest; invalid authority configuration fails the whole command.
Per-source failures use bounded Code values. The existing
`scripts/res416_training_use.py` continues to emit the four-source RES-63 audit.

Loaders must call `authorize_training_bytes(request, content, grant)` immediately
before consuming bytes. It reads the current system UTC clock itself and rechecks
exact committed trust against the provisioned commitment, content and grant.
It accepts no repository or timestamp argument and rejects synthetic material.
The host clock and installed code are trusted operational dependencies.
A saved manifest or its public hash is never a credential: `require_admitted`
now always raises, including for fresh, positive and rehashed diagnostics.
Re-evaluate after any content, purpose, transformation or authority change.

Empirical admission fails closed with `EMPIRICAL_QUALIFICATION_REQUIRED`, even
with independently pinned training rights. This request format has no verified
RES-63 population/provenance/qualification receipt binding, so it cannot establish
an eligible empirical role. All four locked source IDs are also refused under
**every** source class, preserving UNIFESP's qualified-but-not-training-authorized
status and the other three sources' quarantine. This API provides no noncanonical
empirical exception. A future empirical loader needs an independently reviewed
qualification binding; a rights grant or source-class change cannot supply it.
Synthetic positive diagnostics cover text, instructions and engine traces only.

## Next executable mission

Build a development-only SFT constructor using original instructional templates
and qualified RES-71 deterministic operations. Bind every example to operation
registry identity, input lineage, result digest and a pinned training grant;
produce external content-addressed TRAIN shards and independently isolated dev
checks. Reject PSE validation, hidden-final, answers and unapproved benchmark
inputs before construction. Then add a CPU dry-run loader using this admission
API. A subsequent explicitly gated LoRA experiment may consume those shards with
the RES-419 selected model/tokenizer once their own license and training gates
pass. Neither construction nor LoRA is executed in RES-416.

## RES-417 CPU processing

API: `dynamislm.training_data.processing.process_training_inputs(inputs,
exclusion_bundle=raw_bundle_or_none, output_root=external_path)`. Each input is
`(Request, exact_content_bytes, exact_grant_bytes)`. The only implemented
transformation is `("res417-utf8-lines-v1",)`, which the exact RES-416 grant must
independently authorize. Only strict UTF-8 plain scientific text is supported;
PDF, HTML extraction and Unicode/whitespace folding are not implemented. CRLF
and CR become LF. Equations, symbols, numbers, units and all other characters
remain unchanged. Raw and normalized SHA-256 identities remain distinct.

Run the production CLI:

```sh
uv run python -m dynamislm.training_data.process_cli /external/request.json \
  --exclusions /external/exclusions.json --output-root /external/processed
```

The request is a JSON object with only `inputs`, a nonempty list. Each entry has
`source` (the RES-416 source object), `purpose`, `transformations`, `partition`,
`content_path` and `grant_path`. Paths must be outside Git. Use absolute paths;
relative paths resolve from the working directory. There is no manifest,
license override, synthetic permission flag, clock or alternate trust option.
Every call checks live RES-416 admission, including another check immediately
before artifact publication. Current production grants remain empty.

Exclusions have a separate provisioned commitment in
`processing._EXCLUSION_COMMITMENTS`; the production set is deliberately empty.
An independent review must authorize a bundle's exact bytes and complete scope
before a reviewed code release provisions its digest. Training rights do not
confer exclusion authority. No applicant-provided digest list confers authority.
The external bundle has schema `RES417-EXCLUSIONS-1` and `entries`, each with
`identity`, `role`, `text` and the exact UTF-8 text's `sha256`. Required roles are
PSE_VALIDATION, PSE_HIDDEN_FINAL, BENCHMARK_ANSWERS, UNAPPROVED_BENCHMARK and
VALIDATION. The provisioned commitment must represent the complete independently
reviewed exclusion snapshot, including other partitions. Protected text remains
external; receipts contain only digests and roles. Missing/untrusted evidence or
incomplete coverage yields UNQUALIFIED; an invalid trusted bundle is rejected.

Exact-byte and normalized-content duplicates quarantine all affected identities;
the processor never merges measurements or silently picks an evidence survivor.
Repeated source/version identities also quarantine even if their text differs.
Exact protected overlap is CONTAMINATED. Bounded near/partial overlap is
MANUAL_REVIEW. Screening policy `res417-lcs-weighted-cells-v2` uses unchanged
case-sensitive word/punctuation tokens. One dynamic-programming pass computes
the longest common subsequence (LCS) and longest contiguous common token run.
A pair requires review if `4 * LCS >= token_count_a + token_count_b` (equivalent
to similarity `2 * LCS / (count_a + count_b) >= 0.5`) or a contiguous run has
at least 8 tokens. Both lengths and the predicate are symmetric. LCS is at
least the total ordered matches selected by either former SequenceMatcher
orientation, so a previous positive cannot become negative. This screening
policy is more conservative; it makes no scientific-equivalence assertion.

Each request has one immutable production limit of **2,000,000 work units**,
shared by source/source and source/exclusion comparisons. Before a nonexact
pair runs, it reserves `n * m * (1 + min(max_token_length_a,
max_token_length_b))` units. The factor conservatively bounds token-character
equality work per cell plus the constant-size LCS/contiguous-run updates. Each
cell performs one token equality; there is no recursive or greedy matcher.
The receipt records the limit, reserved/consumed units, actual DP cell count,
all comparison attempts, deferred comparisons and budget-exhaustion flag.
Units never exceed the cap, nor can DP cell updates exceed 2,000,000. Completed
comparisons consume their full reservation even if overlap is found early.
Memory for the DP is O(m), at most four rows of 4097 integers.

Source requests are canonically ordered before any comparisons; exclusion
entries are also canonically ordered. This fixes the schedule and makes both
results and accounting invariant to input permutations. Any pair exceeding the
remaining budget returns MANUAL_REVIEW without running the DP, even when the
budget has room for some later smaller pair. No unchecked pair returns NONE.
All such results contribute findings and withhold the batch shard. Exact
normalized SHA-256 identities are still checked even after exhaustion.
Nonexact comparisons with empty token sequences or over 4096 tokens also
require manual review. Each document is tokenized once, retaining at most
4097 tokens; byte scanning/hashing/normalization is linear in the bounded
source and exclusion bytes. Batches and exclusions each have at most 256
entries and each text at most 1,000,000 bytes: at most 512 MB of text preparation
and 98,176 fixed-size digest/pair checks, followed by the shared DP budget.
These are algorithmic bounds, not a wall-clock timeout claim.

Arbitrary semantic paraphrases can evade lexical screening. CLEAN means only
that this batch passed these bounded checks against its provisioned exclusion
snapshot. There is no automatic manual-review clearance path.

All statuses other than CLEAN withhold the entire batch's shard. Exit codes are
0 for CLEAN, 1 for an unqualified/quarantined/review batch, and 2 for rejection.
Output is an external content-addressed directory containing `receipt.json` and,
only for CLEAN, `shard.json`. Both use the unchanged Serialization V3 envelope
(read its `payload`). The directory name is the canonical receipt SHA-256;
receipts bind source/version/class, purpose, grants, raw/normalized hashes,
transformation, exclusion bundle, screening parameters, TRAIN partition and
shard hash. Receipt schema is now `RES417-PROCESSING-2`; Serialization V3 is
unchanged. Every receipt and shard row declares `qualification_scope` as
`BATCH_LOCAL_ONLY`. The receipt has `corpus_qualification: ASSEMBLY_REQUIRED`
and always `split_isolation: UNQUALIFIED`, including for batch-local CLEAN.
The CLI's success status likewise indicates only a completed batch-local run. Writes use private staging and directory rename;
repeated outputs are checked byte-for-byte and never overwritten. Receipts are
not reusable admission tokens. Callers must keep artifacts external and rerun
admission before any later use; a receipt does not grandfather expired rights.

Reproduce the synthetic CPU dry run and adversarial checks:

```sh
uv run pytest tests/test_res417_processing.py -q
./scripts/ci.sh
```

Tests provision both trust boundaries only in isolated temporary repositories
using monkeypatch, with visibly SYNTHETIC content. No production switch enables
that authority. The CLI is exercised through the same test-provisioned boundary;
separate checks prove production still denies those grants. Tests cover changed
bytes, duplicate identities, revoked grants, unsupported transformations,
validation-partition leakage, exact/normalized/near/partial overlaps, missing
protected evidence, forged manifests, symlink paths, output tampering and a
trust change during screening. No real corpus is ingested and no model runs.
RES-71 development SFT construction remains a separate mission after RES-417
integration; formal PSE V1 gates and existing datasets remain unchanged.

Each document identity binds its request, grant, normalized bytes and transform.
This version emits one full-document chunk, with an identity bound to its
parent document and exact normalized UTF-8 byte span `[0, length)`. No arbitrary
scientific sentence/equation splitting occurs. Shard rows carry both identities.
The receipt also pins the processor implementation bytes. Findings and sources
are canonically sorted, so input enumeration order does not change artifacts.

### Corpus-consumer boundary

`processing.authorize_sft_corpus_bytes(receipt, shard)` always raises
`PermissionError(CORPUS_ASSEMBLY_REQUIRED)`. There is no permission flag,
manifest shortcut or provisioned corpus authority. Edited, rehashed, legacy
and reloaded receipts cannot confer global corpus approval. Future SFT
consumers must cross this boundary; reading a development shard directly is
not corpus qualification. No production SFT loader is introduced here.

Future independently trusted corpus assembly must reconcile **all** source
identities, raw/normalized-content digests, document/chunk identities,
partitions and exclusion snapshots across every shard; it must also recheck
live source rights. Neither batch-local CLEAN nor repeated artifact-byte
verification performs that reconciliation. Two separately processed identical
texts with distinct source IDs can therefore produce two development shards,
but neither is admitted by the corpus-consumer gate. No global index, corpus
qualification assertion or new training permission is implemented in RES-417.

Targeted review regressions were executed before their repairs: the supplied
four-token pair failed symmetry; its separately authorized batch permutations
changed CLEAN/MANUAL_REVIEW; a request with repetitive inputs had no cumulative
work accounting; two independent identical-content batches lacked batch-local
qualification scope. The repaired tests additionally falsify budget exhaustion,
permutation invariance, exact matches after exhaustion, token/byte limits,
Unicode notation, conservative retention of former detections and forged or
reloaded corpus qualification. All positive authority remains test-only.
