# PerformanceScience-Eval V1 pre-review lifecycle

This contract implements the RES-115 Phase-B boundary from
[RES-21-DR-001](../decisions/RES21-DR-001-performance-science-eval-v1.md).
It does not change that frozen case contract or the RES-60/62/69/70/71
scientific authorities.

## Lifecycle

```text
CandidateReviewPacket (PENDING_HUMAN_REVIEW)
    -> HumanApprovalRecord (separate, immutable decision)
    -> promote_with_receipt(...)
    -> PromotionResult { BenchmarkCaseV1, CasePromotionReceipt }
```

`CandidateReviewPacket` is a distinct serializable type. It contains the
proposed case meaning, author provenance, contamination/isolation metadata,
difficulty and adversarial metadata, and a complete reviewer checklist. It has
no reviewer identity, approval timestamp, or final split field. Its status has
one valid value: `PENDING_HUMAN_REVIEW`.

An `ADVERSARIAL_MUTATION` packet carries a typed immutable
`CandidateParentBinding` with the exact parent candidate ID, version, payload
hash, origin class, and mutation lineage ID. That binding is part of the child
candidate hash. `validate_candidate_set()` resolves the exact parent candidate,
checks the declared scientific-field delta and preserved primary authority,
rejects cycles or missing parents, and requires matching lineage isolation
metadata. `topological_candidate_promotion_order()` returns a deterministic
parent-before-child order; it does not allocate a split.

The candidate payload hash binds the benchmark/schema target, candidate
identity/version, question/input, expected answer, authorities, refusal/claim/
comparability/scoring/tolerance contracts, proposed provenance,
contamination/isolation, difficulty, and adversarial tags. The proposed
approval digest binds that payload hash to the pending status and frozen
checklist. Approval records must carry both exact digests.

`HumanApprovalRecord` is supplied as a separate immutable decision record.
Promotion requires its digest to validate, an `APPROVED` decision, a reviewer
identity distinct from the packet author, non-empty expertise metadata, a
timezone-aware decision timestamp, candidate ID/version/hash equality, and
equality with the packet's proposed approval digest. A valid record digest
proves record integrity only; it does not prove that the named reviewer
performed the review. `review_event_reference` is reserved for a Phase-C
ingestor to preserve the identifier of an event received from a
human-controlled trust boundary. Supplying that field alone does not
authenticate an event, and the external review workflow is not defined here.

Promotion returns the final case and a canonical immutable
`CasePromotionReceipt`. The receipt binds the exact candidate payload hash and
reviewed-packet digest, approval-record ID and digest, and resulting final-case
payload hash, along with reviewer and timestamp fields. Validation rechecks
every link. The receipt contains no protected source text and assigns no final
split. Promotion writes the validated decision fields into existing
`ExpertReviewMetadata`, creates only an unallocated `SplitBinding`, binds the
final V1 case hash, and runs `validate_case()`.

Mutation promotion additionally requires recursively validated
`ParentPromotionEvidence` for the already promoted parent. Promotion
deterministically substitutes the parent's final case payload hash into
`parent_case_hash`, the `MUTATION_PARENT` authority digest, and the final
`MUTATION` derivation edge. The child receipt binds the exact parent candidate
commitment, parent final case hash, and parent promotion-receipt digest.

## Deterministic checks

Candidate validation resolves RES-60/62/69/70 and RES-71 bindings against the
live registries. RES-71 numeric candidates must preserve the exact registered
reference outputs, units, and tolerance. Core validation takes an explicit
`SourceArtifactResolver` dependency for source evidence. The RES-115 authoring
adapter binds that resolver to the accepted Phase-A registry, checksum
manifest, and canonical retained source store at
`/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/sources/accepted`.

For each source-backed candidate, the resolver must find one exact accepted
registry row and checksum entry, read the corresponding retained
`article.xml.gz`, verify its compressed SHA-256, decompress it, verify the
uncompressed JATS SHA-256 and byte count, and derive excerpt text from the
declared locator. The supported extraction rule is `JATS_TEXT_CONTENT_V1`.
Its structural locator form is
`jats-text-v1:/article[1]/body[1]/sec[2]/p[1]`: each one-based index selects
among direct children with that local tag name, and the first segment must
identify the article root. The extracted value is the exact concatenation of the
selected element's XML text nodes, with no whitespace normalization or
document-wide text search. Candidate excerpt UTF-8 bytes and span digest must
equal that derived value. The Phase-B packet must also include typed source
references and excerpts, artifact/content/span provenance, both document and
span authority bindings, and the registry-bound source-family identity.

The final case validator does not resolve external JATS; that source check is
performed before promotion at the candidate boundary. Final
`BenchmarkCaseV1` scientific semantics remain unchanged; mutation validation
also requires the frozen parent authority to bind the exact final parent hash.

Scoring paths and error attribution reuse the existing final-case validator's
answer contract checks. Candidate packets never receive a final split, and a
candidate cannot be passed to `validate_case()` as a `BenchmarkCaseV1`.

This is a lifecycle foundation only. It does not materialize the Phase-B case
corpus, create any human approval, allocate splits, execute model inference, or
change scientific-engine behavior.

No production human approvals are created by this lifecycle foundation.
Phase C must ingest approval evidence through a human-controlled trust
boundary. An agent-created `HumanApprovalRecord` is not production approval
evidence merely because its record digest validates.
