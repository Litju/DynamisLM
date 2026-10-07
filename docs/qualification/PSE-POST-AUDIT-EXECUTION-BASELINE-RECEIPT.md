# PSE V1 post-audit execution baseline receipt

```text
MISSION=PSE-V1-POST-AUDIT-EXECUTION-BASELINE-001
STATUS=PASS
RECOVERY_ANCHOR=c689d5d057da0d5281d718cb25a7b33d26d2530b
RECOVERY_ANCHOR_TREE=57fe054655b96ec69f751027eba5183ff5173d8b
WORK_BRANCH=work/pse-post-audit-execution-baseline
IMPLEMENTATION_HEAD=1584353825a4888d2ab0fb8b395b7e141feb10d9
RECEIPT_COMMIT=CHILD_OF_IMPLEMENTATION_HEAD
REMOTE_PUSH=NO
INVALID_LOCAL_RES397_HEAD=e2d7f9bd616cb7f01e9c834ff8442e2cb8cb9288 (preserved unmodified as forensic evidence)

POST_AUDIT_AUTHORITY=RES258/369/373/381/383
FIXED_PRE_REVIEW_N=NO
HISTORICAL_ORIGIN_EQUALITY_ACTIVE=NO
HISTORICAL_37X3_ACTIVE=NO
RES223_TOPOLOGY_ACTIVE=NO
RES128_FIXED_DIGEST_GATE_ACTIVE=NO
LEGACY_EXACT_ORACLE_NEW_POOL_GATE=NO

VARIABLE_POOL_AUTHORING_PATH=PASS
INDIVIDUAL_RECIPE_REUSE=SUPPORTED
COLLECTIVE_434_TOPOLOGY_AUTHORITY=NO

SOURCE_AUTHORITY=PASS
RES71_AUTHORITY=PASS
SYNTHETIC_AUTHORITY=PASS
CONTAMINATION_VALIDATION=PASS
ISOLATION_VALIDATION=PASS

RES369_CONSTRAINT_VOCABULARY=UNCHANGED
RES373_ENGINE_REFERENCE_ISOLATION=UNCHANGED
RES381_CANONICAL_CORRECTNESS=UNCHANGED
RES383_SUPPLY_SEMANTICS=CORRECTED

NO_CANDIDATE_HUMAN_APPROVALS_CREATED=YES
NO_PROTECTED_MEMBERSHIP_PERSISTED=YES
NO_BENCHMARK_FREEZE=YES
CANDIDATE_POOL_PERSISTED=NO
EXTERNAL_STORE_WRITES=NONE
SOLVER_RUNS=NONE
DR001_CHANGED=NO
RES71_REFERENCES_CHANGED=NO
SERIALIZATION_V3_CHANGED=NO
HISTORICAL_HASHES_CHANGED=NO

RUFF=PASS
FORMAT=PASS
MYPY_STRICT=PASS (217 source files)
REPOSITORY_POLICY=PASS
FULL_CI=PASS (./scripts/ci.sh at IMPLEMENTATION_HEAD; rerun at RECEIPT_COMMIT)
PYTEST=PASS (1225 passed; RES-383 anchor baseline 1190)
QA_TRACKED_MUTATION=NONE

PSE_V1_COMPLETE=NO
NEXT=VARIABLE_PRE_REVIEW_POOL_CONSTRUCTION
```

## Authority

This baseline implements, and does not amend:

- [RES21-DR-001](../decisions/RES21-DR-001-performance-science-eval-v1.md), the scientific and scoring constitution;
- [RES258-DR-001](../decisions/RES258-DR-001-pse-v1-pool-first-selection-authority.md) and the [supersession map](../decisions/RES258-SUPERSESSION-MAP.md);
- the [pool-first lifecycle](../architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md);
- the RES-369, RES-373, RES-381 and RES-383 receipts in this directory.

The RES-397 branch `work/res-397-materialized-pool-attrition` reactivated the
superseded RES-126/128/222/223 execution path. That branch was not rewritten,
merged, or cherry-picked. Its valid concerns were reimplemented here from the
recovery anchor, one concern per commit.

## Commits

| Concern | Commit |
| --- | --- |
| Variable production-pool validation without a fixed 434 | `397022e` |
| Exact 13-token question-shingle projection | `e68cf37` |
| RES-383 repair-trial parent-provenance fix (from `a3d041a`) | `7c03d8f` |
| Variable pool authoring contracts | `9423cff` |
| Pool-first materialization boundary | `789ad08` |
| RES-383 supply decoupled from historical planned slots | `2fe22ec` |
| Static call-path proof | `1584353` |
| Lifecycle documentation and this receipt | receipt commit |

## Modern execution boundary

```text
ProductionCandidateRecipeV1        one individually authorized recipe
    -> VariablePoolAuthoringPlanV1 explicit variable recipe set (no N, origin, or lineage target)
    -> materialize_variable_pool   existing per-recipe production builders + current gates
    -> ProductionAuthoringCandidatePoolV1 (pending review, bound to the plan digest)
    -> project_variable_pool_selection_candidates -> unchanged RES-369 vocabulary
    -> validate_variable_pre_review_pool (RES258 lower bound N >= 434 + packet gates)
```

A recipe's basis is `HISTORICAL_INDIVIDUAL_RECIPE` or `GOVERNED_SUPPLY_LANE`.
`historical_recipes_from_authoring_inputs` turns the historical production input
into individual recipes. Expert recipes carry their batch, template and cluster
*identity*, but not historical batch membership. Mutation recipes carry an
explicit parent, lineage, operator and stage. Slot totals, the origin vector,
lineage geometry, RES-223 plans and legacy receipts are discarded.

## Removed from the active path

The modern entrypoints are:

- `historical_recipes_from_authoring_inputs`
- `VariablePoolAuthoringPlanV1`
- `materialize_variable_pool`
- `production_source_selection_universe`
- `project_variable_pool_selection_candidates`
- `validate_variable_pre_review_pool`
- `build_live_authority_supply_inventory`
- `assess_authority_supply_inventory`
- `plan_variable_pool`

`tests/test_variable_pool_reachability.py` proves that none of these can reach
the following symbols. The analysis is conservative and AST-based across
modules, it includes a positive control, and it was falsified by injection.

- `build_production_authoring_draft`;
- the fixed 434 skeleton: `_authoring_input_skeleton`, `_semantic_slot_specs`,
  `_engine_slot_specs`, `_synthetic_slot_specs` and `_expert_batch_records`;
- 37x3 or 111 mutation geometry: `_mutation_lineage_specs` and `_author_mutation_packets`;
- the fixed 40-source selection: `_choose_supported_sources`;
- RES-223 plan application, either through `_new_or_resume_private_inputs` or
  anywhere in the `res223_topology` module;
- the RES-128 fixed digest gate: `_validate_res128_feasibility_baseline` and the
  `_RES128_*` constants;
- the RES-225 hooks and the `res225_repair` module, plus the `res249_redesign` module;
- the legacy exact-feasibility and fixed-plan gates:
  `validate_production_exact_feasibility`, `validate_production_exact_feasibility_receipt`,
  `validate_production_hard_feasibility`, `validate_production_candidate_set`
  and `bind_production_authoring_plan`.

`tests/test_variable_pool_materialization.py` replaces each of these with a
failing stub and still materializes a pool.

## RES-383 supply correction

`build_live_authority_supply_inventory` now emits
`PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0`. That schema rejects planned origin
counts, planned lineage counts, and any nonzero `existing_planned_capacity`.
Its lanes are built as follows:

- **Source:** one lane per accepted document. A document that already carries a
  historical recipe is limited to that recipe's cell. Every other document uses
  its eligible cells.
- **Engine:** one lane per RES-71 reference and cell.
- **Expert:** one lane per batch identity.
- **Mutation:** one lane per lineage.

Each of these lanes reports its individual recipes as a lower bound, plus a rule
stating that more capacity needs explicit authority. Synthetic generators are
rule-governed. The assessment reads lane supply.

Historical v1.2 inventories remain readable, and their digests are byte-identical
to the `c689d5d` implementation; that digest is pinned in a test.

The live builder was then run read-only against the external store:

```text
SUPPLY_SCHEMA=PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0
SUPPLY_INVENTORY_DIGEST=sha256:e21545a8a06baaab67f436716a4e448abb575eedca78c9504e29251dfb43f389
PLANNED_ORIGIN_COUNTS=NONE
PLANNED_MUTATION_LINEAGES=0
SOURCE_LANES=55 AVAILABLE / 49 EXHAUSTED
ENGINE_LANES=23 (31 individual recipes)
EXPERT_LANES=146 (240 individual recipes)
MUTATION_LANES=37 (111 individual child recipes)
SYNTHETIC_LANES=3 RULE_GOVERNED
ASSESSMENT=METADATA_REQUIRED
STRUCTURAL_BACKFILL_REQUESTS=0
NECESSARY_POOL_FLOOR=435
DERIVED_POOL_N=NOT_CLAIMED
```

The RES-383 receipt's "one source plus one synthetic backfill" was an artifact
of fixed planned geometry. Under a variable pool, that capacity is now ordinary
authoring supply.

## Individual-recipe reuse evidence

In a read-only, in-memory run, all 434 historical recipes were decomposed and
materialized through `materialize_variable_pool`. Nothing was persisted and no
solver was run. All 434 payload hashes matched the historical builder's packets
in the RES-397 stored pool
`production/candidate-pools/RES-397/a46d93c5…ca86.json`, with 0 mismatches.
This shows that each recipe is reproduced exactly through the current gates. It
says nothing about the collective topology, which remains unqualified and
non-authoritative.

## Retained historical code

The following remain in the repository as historical evidence. They are
unreachable from the modern path:

- `production_authoring.build_production_authoring_draft` and its fixed-434 helpers;
- `res223_topology.py`, `res225_repair.py` and `res249_redesign.py`;
- `scripts/res223_topology.py`, `res224_probes.py`, `res225_repair.py` and `res249_benchmark.py`;
- the RES-222/224 exact-feasibility oracle;
- v1.2 supply semantics.

`selection_pool.plan_variable_pool` is RES-383 authority and is unchanged apart
from the parent-provenance fix.

## Not carried forward from RES-397

- the `scripts/res397_materialized_pool.py` runner;
- the `read_repair_plan` dependency;
- the legacy UNKNOWN bypass;
- RES-223 receipt namespacing;
- the immutable 434 baseline;
- witness-free structural additions;
- the runner's Cartesian trial search;
- the removal sweep on an infeasible base;
- the `/tmp` checkpoint runner;
- the RES-397 acceptance receipt.

The RES-397 private artifacts in the external store were left untouched.

## Tests

New or extended tests:

- `test_variable_pool.py`: contracts;
- `test_variable_pool_materialization.py`: per-recipe equivalence, subset plans,
  fail-closed lanes, and runtime non-reachability;
- `test_variable_pool_reachability.py`: static proof;
- `test_res383_pool_plan.py`: v1.3 supply, the pinned v1.2 digest, and the
  parent-provenance regression, which fails without the fix;
- `test_res369_selection.py`: shingle projection and tamper rejection;
- `test_res115_production.py`: the variable pool gate.

## Next phase

The next phase is variable pre-review pool construction. It starts from v1.3
supply and authors a `VariablePoolAuthoringPlanV1` with no fixed N, then:

1. materializes the pool;
2. qualifies the base and every single removal with the pool-feasibility profile;
3. qualifies the independent CRITICAL reserve;
4. confirms canonical selection under the production solver profile;
5. hands the pool to human review.

Backfill only follows an observed deficit, using governed lanes and an exact
witness. Topology repair is not a default phase. PSE V1 is not complete.
