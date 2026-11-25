# A0.3 internal evaluation protocol v2

RES-771 R3, comment `2490dfe7-c10d-4f35-8541-007b3e510db8`, authorizes
`AI_ASSISTED_OWNER_ADJUDICATED` for RES-774. ChatGPT recorded the owner's
explicit decision. The evidence class is `INTERNAL_OWNER_ADJUDICATED` and
independence is `NONE`.

This amendment incorporates the frozen v1 protocol and configuration by
digest. It supersedes v1's owner-only authorship rule for v2. R1 and R2
apply as approved in RES-771 comment `17a5c4fe-b479-46b2-a72d-fe813154d52b`.
The v1 artifacts, scientific scope, contamination and distinctness checks,
endpoints, statistical rules, thresholds, support, arms, blinding, and
compute gates continue unchanged. RES-746 remains separate.

## Draft and review

AI may draft episodes, questions and proposed gold under expert guidance.
Draft without access to exposed questions, training templates, candidate
outputs or decoder comparisons. A fresh reviewing context interprets the
question and evidence before seeing the proposed gold. Record disagreements
and revisions. For execution controls compare the deterministic engine result
with independent signed later-minus-earlier arithmetic. Human scientific
adjudication covers every retained item and any unresolved disagreement.

The protected `provenance.json` has `authoring_model` (provider and the
model identifier actually available), `generation_configuration` (object
with the known settings and explicit disclosure of settings the host does
not expose), and an `items` array. Each entry has `item_id`, `provenance`,
`proposed_gold` (judgment and rationale), `critique`, `revision_history`
(array of text entries, empty if unrevised), and `owner_disposition`
(`ACCEPTED` or `REVISED`). Final gold retains the v1 row format. An
accepted proposal must match final gold. A revised one must differ and
carry revision history. Rejected candidates stay outside the retained packet.
The owner reviews the final inputs and records every disposition before
authenticating the packet. A draft and a signed approval are distinct records.

## Owner authentication and sealing

Use the v2 attestation schema `DYNAMISLM_A03_INTERNAL_ATTESTATION_V2`
with `owner_id`, `authorship`, `gold_recorded_before_inference`,
`no_a02_template_or_generator_reuse`, and `independence` alongside
`schema`. The two attestations must be true. V2 accepts only the R3
authorship classification. Keep provenance and the detached
`owner-approval.sig` with the protected packet, outside Git.

The owner or trusted custodian provisions the owner's Ed25519 public key
through a separately authenticated channel. Keep it outside the packet.
Use the same trusted key for sealing, releasing and scoring. The verifier
proves that the holder of the provisioned private key signed the exact
packet bytes and per-item dispositions. Personal adjudication, the time
relative to inference, and control of the trust root remain owner/custodian
responsibilities.

Print the exact canonical approval payload before the owner signs it.

```sh
uv run python -m scripts.a03_internal_seal "$packet" --approval-payload > "$approval"
ssh-keygen -Y sign -f "$owner_private_key" -n dynamislm-a03-owner-v2 "$approval"
cp "$approval.sig" "$packet/owner-approval.sig"
uv run python -m scripts.a03_internal_seal "$packet" --owner-key "$trusted_owner_public_key" --blind-out "$blind"
```

The signature binds the protocol and hashes of the protected inputs,
including every final gold row. Set the packet cutoff at successful sealing.
Keep only the existing gold-free export in the blinded store. Use
`--protocol-version 2` for run-manifest creation and compute estimation.
Use `--owner-key` for gold release and scoring. The scorer verifies that the
sealed and run identities agree. V1 retains its historical format and
verification path for reproducibility.
