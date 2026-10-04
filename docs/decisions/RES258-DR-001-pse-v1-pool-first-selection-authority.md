# RES258-DR-001 — PSE V1 pool-first selection authority

- **Mission:** `PSE-V1-POOL-FIRST-AUTHORITY-AMENDMENT-001`
- **Authority entry:** `d876b7aea2b77665bf5775111c96dc354838cb27`
- **Decision basis:** RES-256 `PASS`; RES-254 human decision `RESTORE_POOL_FIRST_GE434`
- **Scope:** specification and authority only

## Decision

Adopt a qualified, variable pre-review pool and select the final V1 benchmark
jointly after review. This record amends the construction and selection
lifecycle only. The scientific coverage constitution in
[RES21-DR-001](RES21-DR-001-performance-science-eval-v1.md) remains unchanged.
This record does not authorize solver implementation, candidate authoring or
materialization, human review, split persistence, or protected-store changes.

The active construction authority is the combination of this record and the
pool-first lifecycle in
[`PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md`](../architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md).
The [supersession map](RES258-SUPERSESSION-MAP.md) classifies earlier
implementation assumptions and retained historical evidence.

## Frozen authority summary

```text
PRE_REVIEW_POOL_N=VARIABLE_GE434
FINAL_SELECTED_N=434
FINAL_SPLITS=PUBLIC_DEVELOPMENT:260,FROZEN_VALIDATION:87,HIDDEN_FINAL:87
REJECTION=REMOVE_FROM_FINAL_ELIGIBILITY
FINAL_COMPOSITION=RES126_BOUNDS
EXPERT_AUTHORED_SEMANTIC_SCOPE=FINAL_SELECTED_ONLY;MAX=240
MUTATION_PARENT_PROVENANCE=REQUIRED
MUTATION_PARENT_CO_SELECTION=NO
MUTATION_RELATED_SELECTED_MEMBERS=SAME_SPLIT
MUTATION_CELL_INHERITANCE=KEEP_SAME_CELL_BY_DEFAULT
CRITICAL_FINAL_MINIMUM=DR001
CRITICAL_POOL_POLICY=INDEPENDENT_RESERVE_BEFORE_FINAL_SELECTION
POOL_RESERVE_POLICY=STRUCTURAL_LOCAL_RESERVE_PLUS_TARGETED_BACKFILL
PSE_V1_ROLE=COVERAGE_PLUS_ADVERSARIAL_EXAM
PSE_V1_PRIMARY_ROLE=SCIENTIFIC_CAPABILITY_COVERAGE_EXAM
PSE_V1_SECONDARY_ROLE=ADVERSARIAL_SCIENTIFIC_BEHAVIOR_EXAM
HIGH_PRECISION_CELL_PERFORMANCE_CLAIM=NOT_AUTHORIZED
FINE_GRAINED_MODEL_RANKING_CLAIM=NOT_AUTHORIZED
PRODUCTION_SOLVER_CHANGED=NO
CANDIDATE_CONTENT_CHANGED=NO
MATERIALIZATION_RUN=NO
PROTECTED_STORES_MODIFIED=NO
```

## Unchanged constitution

RES21-DR-001 remains the scientific and scoring constitution, including its
population, capability and family scope, authorities, contamination rules,
coverage requirements, and split semantics. Its serialization and historical
hashes are not changed by this amendment. The final 434-case target follows
that constitution's executable full-coverage minimum; it does not set the
pre-review pool size.

For every critical-error class required by DR-001, the final selected benchmark
must retain at least one eligible case in each protected split where DR-001
requires it (`FROZEN_VALIDATION` and `HIDDEN_FINAL`). This is the final
benchmark minimum. Pool qualification also requires an independent reserve
before final selection as a reliability condition; that reserve does not add a
new DR-001 final-count requirement.

## Final-selection hard constraints

The pool-first lifecycle separates pool qualification from final selection:

| Constraint | Final-selection authority |
| --- | --- |
| Final count | Exactly 434 selected cases |
| Splits | `PUBLIC_DEVELOPMENT=260`, `FROZEN_VALIDATION=87`, `HIDDEN_FINAL=87` |
| `EXPERT_AUTHORED_SEMANTIC` | `<= 240` selected cases |
| `SOURCE_BACKED_EVIDENCE_EXTRACTION` | `>= 40` selected cases |
| `DETERMINISTIC_ENGINE_DERIVED` | `>= 30` selected cases |
| `DETERMINISTIC_SYNTHETIC` | `>= 12` selected cases |
| `ADVERSARIAL_MUTATION` | `>= 60` selected cases |
| `MUTATION_LINEAGES` | `>= 20` represented lineages |
| Coverage, authority, contamination, isolation | DR-001 and the live registered authorities |
| Protected critical errors | DR-001 minimum per required protected split |

These composition bounds are enforced on the jointly selected final 434.
Candidate authoring and the qualified pool may exceed them to provide eligible
reserve and backfill options. The exact composition observed in earlier
prototypes has no minimum or equality authority.

## Pool qualification and review

The pre-review pool cardinality is variable and must be at least 434. There is
no fixed pre-review count. Pool qualification validates each candidate's
scientific identity, source and provenance, contamination status, isolation
identity, mutation lineage, and eligibility, then qualifies an independent
reserve inventory before review.

The reserve is structurally derived from actual eligible components and
governed constraints. It is a reliability and pool-qualification target, not a
fixed oversupply count or a final composition rule. After review, a rejected or
unapproved candidate is removed from final eligibility. It is never
reclassified as `PUBLIC_DEVELOPMENT` to absorb review attrition.

If the approved eligible pool cannot support a valid exact final selection,
use targeted governed backfill. Each backfilled candidate must pass the same
qualification and human-review lifecycle. Selection remains blocked until an
independent validator proves a compliant final set.

## Mutation and isolation semantics

Every mutation retains immutable parent provenance binding the exact parent
identity and payload hash, along with its mutation lineage and required
authority. Parent provenance is not a final-selection dependency: a mutation
may be selected even when its parent is not selected. If related mutation
lineage members are selected, isolation keeps those selected members in the
same split. Same capability-by-family cell inheritance remains the default;
an operator-specific exception requires explicit authority. Mutation counts
are governed by the final lower bounds above, not by a fixed lineage-size
geometry.

Pool qualification, approved-pool selection, final D/V/H allocation, and
independent validation must use one semantic constraint vocabulary. A second
final allocator with weaker or different rules is not authorized. This record
specifies that requirement; RES-3k implements it.

Engine-reference identity from RES-71 must become an explicit isolation
identity. Incidental exact-shingle coupling is insufficient. Implementation is
deferred to RES-3l.

## PSE V1 claim ceiling

PSE V1's primary purpose is scientific capability coverage; its secondary
purpose is adversarial scientific-behavior evaluation. Its validation and
hidden allocation has one case per capability-by-family cell, which supports
coverage claims. It does not authorize high-precision cell-level performance
estimates or fine-grained model ranking without additional statistical
qualification.

## Historical evidence and supersession

The exact origin vector `240/40/31/12/111`, the `37 lineages × 3 children`
topology, and results tied to those specific candidate designs remain
historical evidence only. They are not required final composition or mutation
topology. Prior feasibility proofs and reliability measurements remain valid
for the exact inputs they evaluated; they do not establish feasibility,
reserve sufficiency, or membership for a later reviewed pool.

See [RES258-SUPERSESSION-MAP.md](RES258-SUPERSESSION-MAP.md) for the
RES-126/223/225/249/252 disposition. RES-257 preserved the prior WIP on the
separate archival ref `archive/res253-res252-wip-fdb6c94`; this mission does
not reuse those commits.
