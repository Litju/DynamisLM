# A0.3 internal evaluation protocol v3

Version 3 replaces only the mandatory Ed25519 signature gate of v2 with a
recorded owner-approval receipt. It is authorized by the owner-directed R4
decision in RES-771 comment `33488998-98dd-45f4-9934-9591a85b5b08` (26 November
2026). That entry was transcribed by the assistant at the owner's explicit
instruction. It is not personally typed by the owner and it is not an
independent review.

This protocol incorporates v1 and v2 by digest. The evidence class remains
`INTERNAL_OWNER_ADJUDICATED` and independence remains `NONE`. Scientific scope,
strata, cluster and item minimums, distinctness and contamination checks,
endpoints, populations, support, statistics, thresholds, arms, blinding,
gold-free stop rules, gold release and the decision rule are unchanged. No
inference, allocation, publication or claim of independent validation is
authorized by this protocol.

## Approval authority and its limit

For this single-owner internal alpha, the approval authority is the dated,
explicit owner authorization recorded in the connected Linear workspace and
bound to the exact protected inputs. Cryptographic signatures, private keys,
passphrases, trust-root provisioning and additional reviewers are not required
for v3.

SHA-256 establishes artifact identity and integrity against recorded digests.
It does **not** establish who personally reviewed content, and the receipt is
not a cryptographic proof of identity or non-repudiation. The receipt must say
so and must reject any claim of independent or cryptographic authentication.
V1 and v2 bytes, verification paths and historical results remain intact. No
v2 signature is bypassed or forged.

## Approval receipt

The protected packet carries `owner-approval-receipt.json` with schema
`DYNAMISLM_A03_INTERNAL_OWNER_APPROVAL_RECEIPT_V3`. It records:

- `owner_id`;
- the exact Linear decision (`issue`, `comment_id`, `recorded_at`);
- the approval `scope`;
- `attribution: AI_ASSISTED_OWNER_ADJUDICATED`;
- `authentication: RECORDED_LINEAR_OWNER_APPROVAL` and
  `cryptographic_signature: false`;
- `independence: NONE`;
- the SHA-256 of the canonical v3 approval payload;
- the SHA-256 of every protected input that the payload covers;
- `supersedes`: the exact v2 payload digest, the v2 protocol and config
  digests, the same five protected-input digests and
  `scientific_inputs_equal: true`.

The v3 approval payload is canonical JSON over the protocol and config
identity plus the five protected inputs (`scenarios.jsonl`, `requests.jsonl`,
`gold.jsonl`, `attestation.json`, `provenance.json`). It contains no receipt
and no signature, so it is not self-referential.

The `supersedes` block is a deterministic equivalence proof. Sealing refuses
unless every reviewed scientific and provenance digest equals the value in the
already accepted v2 payload. If `--prior-payload` is supplied, the sealer also
recomputes that payload from its exact bytes and requires the recorded v2
digest. A change to a scenario, question, gold judgment, attestation or
provenance row is a scientific change and cannot be migrated by this receipt.

## Sealing and release

Write the v2 payload once, then materialize the receipt from it. Print the v3
payload digest and record the exact input digests with the protected evidence.
Seal without any owner key:

```sh
uv run python -m scripts.a03_internal_seal "$packet" \
  --prior-payload "$v2_payload" --blind-out "$blind"
```

The sealer refuses a missing, malformed, altered or mismatched receipt, a
receipt that claims independence or cryptographic authentication, an input
digest mismatch, a superseded-input mismatch and any v2 signature bypass. Use
`--protocol-version 3` for run-manifest creation and compute estimation. Gold
release and scoring require no key for a v3 packet; supplying one is refused.
V2 continues to require `--owner-key` and its detached signature.

The receipt and the exact v2 payload remain with the protected evidence
outside Git. The blinded export is unchanged from v1 and v2.
