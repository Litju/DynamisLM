# RES-523 Production-Compatible Repeat Allocation Proposal

**State: PROPOSED. Owner approval: PENDING. Materialization: not authorized.**

This versioned replacement resolves the production identity failure in the
original RES-523 proposal. The original plan remains recorded as frozen and
approved at
[`RES-523-REPEAT-ALLOCATION-AUTHORITY.md`](RES-523-REPEAT-ALLOCATION-AUTHORITY.md),
with plan digest
`sha256:240edcc8afe8f44c9d7fbd82b6c46b4e40408e329cf943d949beeabaa90f4398`.
Its candidate IDs use `PSE-V1-REPEAT-CANDIDATE:` and fail the production
identity validator, which requires IDs matching
`PSE-V1-CANDIDATE:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`. That is a producer
namespace mismatch; the production validator is unchanged. The original plan
is incompatible with production and is superseded for execution by this
proposal. Its approval does not transfer.

## Replacement identity and scope

The replacement plan schema is `RES523-REPEAT-ALLOCATION-PLAN@2.0.0`, and its
candidate-ID derivation is `PSE-REPEAT-CANDIDATE-ID@2.0.0`. It derives IDs under
`PSE-V1-CANDIDATE:RES523:REPEAT:`. The machine-readable proposal contains the
complete ordinal-to-ID inventory and its digest:
[`res523_repeat_allocation_replacement_proposal.json`](../../reports/performance_science_eval/res523_repeat_allocation_replacement_proposal.json).

| Field | Replacement value |
|---|---|
| Plan status / owner approval | `PROPOSED` / `PENDING` |
| Plan digest | `sha256:b0c3bc4a07c167a8bb266c082d65854cd50a2f82dbae5f5f18d1e57bb7f53b82` |
| Protocol digest | `sha256:a836d62a1aa47aa2c738182282278c9e818a122bac3224ba51b3de922b17ceb4` |
| Proposal report digest | `sha256:3d4ea36bfca35aa1ffc8d4676ae486f08daf2cb18554ffa43085a221e12b1950` |
| Ordinals / count | `0..47` / `48` |
| Cell / split | `C08:F05` / `PUBLIC_DEVELOPMENT` |

The real production identity validator accepted all 48 IDs. Their length is
95 characters; the production regex permits at most 145. All 48 also passed
`ProductionCandidateRecipeV1` construction and strict production seed
namespace parsing. These checks construct recipe metadata only; they do not
author packets or generate candidate payloads or seed values. There are zero
collisions against the 155 tracked IDs plus the historical one-per-cell ID.

## Compatibility evidence

The replacement binds the same upstream sources and scientific authority as
the original plan:

| Source | Digest |
|---|---|
| `res407_governed_structural_comparison.json` | `sha256:c3669eb5c1823147b5a45d617b6c9270c1956a7b02cc69bfe5e230c332e9e231` |
| `res407_real_c08_sufficiency.json` | `sha256:8906032d404a81d56f576ef0d91523c5752d5cc78f266581f2555f6fe8178560` |
| `res407_c08_generator_qualification.json` | `sha256:b8656213636aef2ab3fc179b03eb6079b6073e9b67b1345687068db7254dec3b` |
| `res407_c08_repeat_authority.json` | `sha256:493554bd3739ae1bb443318d74ec510b708ce514ba30d72c6aa889a588550999` (`UNKNOWN`) |

The RES-407 structural vector digest remains
`sha256:f312934b6455e1ebd379471fd07e93fad8b6d53caf304c63f50bac58099c1923`.
Its selection features remain `CELL(C08,F05)`, critical errors
`FALSE_SCIENTIFIC_ACCEPTANCE` and `INVENTED_NUMERICAL_SCIENCE`, those same two
row errors, and `ROW_TAG(C08,NONFINITE_INPUT)`. Candidate IDs do not contribute
to that feature vector.

Changing IDs changes the derived per-candidate source-family, artifact, and
training-exclusion identity strings. These remain unique across the 48 IDs.
The shared colocation identities remain the public-development isolation
cluster, `pse-v1-synthetic-refusal-public_development` generator family, and
`agent-process:codex:RES-115-CASE-AUTHORING-001B` author batch. The existing
449-candidate evidence records four members in the shared generator family
and public cluster, with no matching author batch; those relation counts are
unchanged. Seed blocks and their split-qualified namespaces are unique. Exact
13-token shingle and other payload-dependent relationships remain unknown
until materialization, as in the original structural proof; the existing
stop-on-collision policy remains in force.

The digest dependency is acyclic: the allocation authority digest produces
seed-block identities; the plan digest commits their inventory and the v2
derivation version; candidate IDs then derive from that plan digest and their
seed-block identities. Candidate IDs are excluded from the plan payload and
included in the later proposal report digest.

The original approved JSON and RES-407 evidence were not changed. This
replacement remains pending owner review, and no candidates or seeds were
materialized.
