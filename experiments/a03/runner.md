# A0.3 paired evaluation operation

The registered scientific rules are in [prospective-protocol.md](prospective-protocol.md).
This implementation separates blinded generation from adjudicated dispatch. The runner
never takes a gold or adjudication path. Give its operating identity only the blinded input
and output paths. After the custodian archives the complete output bytes and commitment,
a separate scorer identity can receive the packet. Local credentials or file permissions
held by the same operator do not establish independent custody.

## Blinded generation

Use a clean exact checkout and private directories outside Git. The custodian exports each
registered request through `a03_prospective_run.blind_request`, in frozen order, as
`requests.jsonl`. The trusted resolver supplies a matching `sources.jsonl` with
`item_id` and `bound`, where `bound` is canonical Serialization V3 JSON text for a
`BoundRequest`. Qualified observations bind the immutable source digest, canonical
longitudinal record and observation digests, exact device, protocol and unit. Unresolved slots
follow the qualified prefix and are omitted from the model prompt.

Use `run_manifest(PROSPECTIVE, requests_bytes, source_bytes)` and store the canonical
object in `run.json`. Exchange its exact byte SHA-256 through the custodian's authenticated
channel. The model snapshot and adapter must already be local and match the D0 file pins.
The entry point is:

```text
python -m scripts.a03_prospective_run BLIND OUTPUT --manifest-sha256 DIGEST \
  --snapshot MODEL_SNAPSHOT --adapter STEP_510 --seconds SECONDS
```

Resume only with the externally retained digest of an intact prefix. Torn checkpoints
stop without truncation. An output commitment appears only after all arm rows are present.
The host must adopt the checkpoint and commitment into the external append-only archive.

## Gold release and scoring

The custodian supplies `release.json` outside the blinded directory and an authenticated
exact byte digest. The release binds schema `DYNAMISLM_A03_GOLD_RELEASE_V1`, mode
`PROSPECTIVE`, `output_commit_sha256`, the existing sealer receipt as `packet`, and
the exact digest of `custodian-attestation.json` as `custodian_attestation_sha256`.
The signed attestation and authenticated delivery are the external authority for human
independence, source rights, exposure checks and custody. The scorer checks their binding.

```text
python -m scripts.a03_prospective_score BLIND OUTPUT RELEASE REPORT \
  --manifest-sha256 DIGEST --commit-sha256 DIGEST --release-sha256 DIGEST \
  --tokenizer MODEL_SNAPSHOT
```

The scorer verifies the committed output first, then reproduces the registered seal.
It replays each model action through RES-70 with an additional veto immediately before
dispatch. If the adjudicated control forbids the attempted operation, the scorer records
the first violation and stops before that operation runs. The result retains per-item
traces, endpoints, paired contrasts and cluster estimates. No final-answer metric exists.
The scripted CPU fixture exercises these paths without model weights under
`DEVELOPMENT_ONLY`, which never emits a prospective study decision.
