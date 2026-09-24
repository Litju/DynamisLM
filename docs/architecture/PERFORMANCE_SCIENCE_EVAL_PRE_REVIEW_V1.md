# PerformanceScience-Eval V1 pre-review lifecycle

This contract implements the RES-115 Phase-B boundary from
[RES-21-DR-001](../decisions/RES21-DR-001-performance-science-eval-v1.md).
It does not change that frozen case contract or the RES-60/62/69/70/71
scientific authorities.

## Lifecycle

```text
CandidateReviewPacket (PENDING_HUMAN_REVIEW)
    -> HumanApprovalRecord (separate, immutable decision)
    -> promote_to_benchmark_case(...)
    -> BenchmarkCaseV1 (unallocated split)
```

`CandidateReviewPacket` is a distinct serializable type. It contains the
proposed case meaning, author provenance, contamination/isolation metadata,
difficulty and adversarial metadata, and a complete reviewer checklist. It has
no reviewer identity, approval timestamp, or final split field. Its status has
one valid value: `PENDING_HUMAN_REVIEW`.

The candidate payload hash binds the benchmark/schema target, candidate
identity/version, question/input, expected answer, authorities, refusal/claim/
comparability/scoring/tolerance contracts, proposed provenance,
contamination/isolation, difficulty, and adversarial tags. The proposed
approval digest binds that payload hash to the pending status and frozen
checklist. Approval records must carry both exact digests.

`HumanApprovalRecord` is supplied as a separate immutable decision. Promotion
requires its digest to validate, an `APPROVED` decision, a reviewer identity
distinct from the packet author, non-empty expertise metadata, a timezone-aware
decision timestamp, candidate ID/version/hash equality, and equality with the
packet's proposed approval digest. Promotion then writes the validated
approval values into the existing `ExpertReviewMetadata`, creates only an
unallocated `SplitBinding`, binds the final V1 case hash, and runs unchanged
`validate_case()`.

## Deterministic checks

Candidate validation resolves RES-60/62/69/70 and RES-71 bindings against the
live registries. RES-71 numeric candidates must preserve the exact registered
reference outputs, units, and tolerance. Source-backed candidates must resolve
their document and stored-artifact identity/digest through the accepted
Phase-A source registry and checksum manifest. Every excerpt must bind its
document version, artifact ID/digest, exact excerpt digest, typed source
reference, provenance, and source-family isolation identity. Human review still
checks that the excerpt text supports the claim at its locator.

Scoring paths and error attribution reuse the existing final-case validator's
answer contract checks. Candidate packets never receive a final split, and a
candidate cannot be passed to `validate_case()` as a `BenchmarkCaseV1`.

This is a lifecycle foundation only. It does not materialize the Phase-B case
corpus, create any human approval, allocate splits, execute model inference, or
change scientific-engine behavior.
