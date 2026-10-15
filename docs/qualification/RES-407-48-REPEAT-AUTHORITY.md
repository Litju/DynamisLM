# RES-407 C08 48-repeat authority checkpoint

This checkpoint qualifies whether the current governed authoring authority permits
48 distinct instances of the accepted `C08:F05` synthetic public-development
archetype. It does not generate candidates, materialize seeds, or repeat the
structural optimization.

## Result

| Field | Result |
| --- | --- |
| Entry head | `856db4adff14531b568397d07c8d17f46824a93a` |
| Structural witness | `FEASIBLE`, minimum additions `48`, cardinality optimality `PROVEN` |
| Lane / cell / split | `synthetic:pse-v1-synthetic-refusal-public_development` / `C08:F05` / `PUBLIC_DEVELOPMENT` |
| Repeat authority | `UNKNOWN` |
| Authorized repeat count | minimum `1`, maximum `UNKNOWN` |
| 48-repeat plan | Not created; repeat authority is unknown |
| Materialization readiness | `NO` |
| Authority expansion readiness | `YES` |
| Concrete candidates / materialized seeds | `0` / `0` |

`RULE_GOVERNED` capacity counts unique split-locked seed blocks. The current lane
has no finite capacity number, but null finite capacity does not authorize an
unbounded count. The authoring path currently emits one recipe per lane/cell;
its candidate ID and seed-block formulas have no repeat ordinal. The governance
record requires unique seed blocks but leaves the repeat count and allocation
sequence unspecified. Implementation capacity therefore does not establish
permission for 48.

The current capability remains `UNRESOLVED`. A future explicit finite bound
below 48 would prove the current repair structurally insufficient because the
accepted minimum is 48. Creating a deterministic plan also requires explicit
authority for the candidate-ID and seed-block ordinal formulas; a numeric
ceiling by itself is not enough.

## Authority and identity contract

The report binds the live C08 lane and generator authority, generator ID/version
and output contract, the F05 generic-refusal path tied to the live RES-71
no-operation reference, the split-qualified seed namespace, the current recipe
and candidate-ID rules, the public split lock, the source-family derivation,
and the existing governed geometry and supply inventory receipts.

Two planned cases are distinct only when their candidate IDs, payload digests,
seed blocks, and seed namespaces are unique. Candidate-ID uniqueness alone is
insufficient. Source-family IDs, candidate artifact IDs, and training-exclusion
IDs must also be unique. Instances intentionally share the public isolation
cluster, generator family, and authoring-process identity described by the
qualified structural contract.

The persisted collision policy rejects duplicate candidate IDs, payloads,
seed blocks, or namespaces; unexpected contamination-identity collisions;
exact 13-token shingle collisions within the staged batch or against the
existing pool; and any difference in lane, cell, split, generator, authority,
or relation/colocation identities. Any violation stops and invalidates the
whole materialization attempt. It does not substitute a seed.

The deterministic ordinal-to-candidate/seed derivation is gated on explicit
authority for at least 48 and for the exact candidate-ID and seed-block
formulas. Its planner and collision checks are covered by focused tests, but no
current C08 repeat plan was produced because the live repeat maximum and
ordinal-allocation authority are unspecified.

## Evidence

Machine-readable report:
[`res407_c08_repeat_authority.json`](../../reports/performance_science_eval/res407_c08_repeat_authority.json)

```text
DISTINCTNESS_CONTRACT_DIGEST=sha256:3f57fac2adf0cea57af50655b5c621693d80ffdda8f8b06ace53d5d68c2203ab
REPEAT_AUTHORITY_EVIDENCE_DIGEST=sha256:4ee01df7c97eafe1d52ee7f9031394dcfc35658daf359cef2e9068c06e435e56
C08_48_REPEAT_PLAN_STATUS=NOT_CREATED_REPEAT_AUTHORITY_UNKNOWN
C08_48_REPEAT_PLAN_DIGEST=None
PLANNED_REPEAT_COUNT=0
COLLISION_POLICY_DIGEST=sha256:953a23cbb2aac06c3162e6134e61946ac83072ae7e87d666ff95573755774386
REPORT_DIGEST=sha256:493554bd3739ae1bb443318d74ec510b708ce514ba30d72c6aa889a588550999
```
