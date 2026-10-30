# RES-416 training-source admission

This boundary prepares data loading; it does not authorize training runs. PSE V1
remains SCIENTIFIC_NO_GO. The four RES-63 empirical audit decisions are unchanged.

## Trust installation

`registries/training_authority.json` is read from the exact Git HEAD, never from
working-tree edits or applicant metadata. It initially contains no grants.
Repository governance is the trust root, as for the existing source registries;
use only a reviewed repository revision. A malicious repository administrator or
modified Python installation is outside this boundary's trust model.

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

`admit_sources` takes tuples of `(Request, exact_content_bytes, exact_grant_bytes)`,
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

Loaders must call `authorize_training_bytes` with the current UTC evaluation time
immediately before consuming bytes. It rechecks committed trust, content and grant
and rejects synthetic material. A saved manifest, its hash, or `require_admitted`
alone is not an authority credential; no unsigned saved receipt is trusted.
Re-evaluate after any HEAD, content, purpose, transformation or authority change.
Synthetic acceptance is available only for explicit test-result inspection;
production byte release rejects synthetic grants.

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
