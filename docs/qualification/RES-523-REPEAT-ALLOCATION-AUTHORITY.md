# RES-523 C08 synthetic repeat allocation authority

**Decision state: PROPOSED. Owner approval is required and pending.** The prior
RES-407 repeat authority remains `UNKNOWN`; this proposal does not authorize
materialization.

## Authority basis

RES-407's digest-checked structural result is feasible at 48 additions, proves
47 infeasible, and records cardinality optimality. Its winning allocation is
48 synthetic repeats in `C08:F05`, locked to `PUBLIC_DEVELOPMENT`, on
`synthetic:pse-v1-synthetic-refusal-public_development`. The source report and
both trial digests are bound in the machine-readable record at
[`res523_repeat_allocation_authority.json`](../../reports/performance_science_eval/res523_repeat_allocation_authority.json).

The repeat protocol is generic and contains no repeat count. The count 48 and
the zero-based ordinals `0..47` belong to the separate RES-407 campaign plan.
The protocol binds its parent lane and generator authority, generator family
and version, allowed capability/family/split, ordinal and identity derivation
versions, collision policy version, and pending approval state.

Protocol digest: `sha256:21230fb9bca4e70224973fe6d8d862cac31c0d9d1e1d621a5883efe75b32a140`

Allocation plan digest: `sha256:240edcc8afe8f44c9d7fbd82b6c46b4e40408e329cf943d949beeabaa90f4398`

## Deterministic identities

Each planned seed-block identity derives statelessly from the allocation
authority digest, protocol digest, lane, cell, locked split, generator version,
and ordinal. Candidate IDs use a separate namespace and bind the repeat
protocol digest, final allocation plan digest, lane, cell, split, ordinal,
planned seed-block identity, and generator identity/version. The derivations
are independent of execution order and use no mutable counter.

The plan and report contain the exact ordinal inventory and digests of the
derived identity inventories, but omit the per-ordinal seed-block and candidate
IDs. No seed values or candidate payloads are generated. The checks produced
48 unique planned seed-block identities, 48 unique planned candidate IDs, and
zero collisions with the tracked historical candidate IDs and the historical
one-per-cell ID namespace.

## Distinctness and materialization boundary

Before materialization, the plan guarantees only:

- a unique ordinal;
- a unique planned seed-block identity;
- a unique planned candidate ID; and
- the exact lane, cell, and split binding.

It does not guarantee unique payloads, shingle independence, no contamination
collisions, no unexpected relation edges, or independent generated text.
Those checks remain mandatory at materialization time.

The frozen collision policy stops and invalidates the whole materialization
attempt on a candidate-ID or seed-block collision, prohibited duplicate
payload, exact-shingle or contamination conflict, wrong feature vector,
unexpected colocation/relation behavior, or invalid generator result. A failed
ordinal cannot be replaced by another ordinal. For example, failure of ordinal
17 stops the attempt; proceeding with ordinal 48 would require a new versioned
allocation decision and owner approval.

Collision policy digest: `sha256:e2cdbdd0788e497cb7bde3187192cbd93b5592ed10d0cd10f990a2fa12b7647c`

## Approval and execution state

`OWNER_APPROVAL_REQUIRED=YES` and `OWNER_APPROVAL_STATUS=PENDING`. No approval
identity, signature, or timestamp is asserted, and the plan is not frozen.
`CONCRETE_CANDIDATES_GENERATED=0`, `SEEDS_MATERIALIZED=0`, and
`READY_FOR_MATERIALIZATION=NO`.
